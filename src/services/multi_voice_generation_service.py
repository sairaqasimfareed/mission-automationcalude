"""Voice generation that can read one scene with several voices.

A scene whose blueprint carries `line_blueprints` (a voice-cast scene: narrator, judge, Joan...) has each line
generated through the ordinary single-voice path, then the lines are joined into ONE audio file and returned as
ONE track - so the clip sizing, the voice stage's positions, the render and the subtitles see exactly what they
always saw: one voice track per scene. A scene without line blueprints is handled by the unchanged parent.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from src.models.resolved_voice_blueprint import (
    ResolvedVoiceBlueprint,
    VoiceBlueprintResolutionStatus,
)
from src.models.voice_generation import VoiceGenerationResult, VoiceGenerationStatus
from src.services.audio_join_service import LINE_GAP_SECONDS, join_audio_files
from src.services.voice_generation_service import VoiceGenerationService
from src.shared.dry_run_placeholder import is_dry_run_placeholder


class MultiVoiceGenerationService(VoiceGenerationService):
    def generate(
        self,
        blueprint: ResolvedVoiceBlueprint,
        *,
        start_time_seconds: float = 0.0,
        provider_name: str | None = None,
    ) -> VoiceGenerationResult:
        if not blueprint.line_blueprints:
            return super().generate(
                blueprint,
                start_time_seconds=start_time_seconds,
                provider_name=provider_name,
            )

        results: list[VoiceGenerationResult] = []

        for line_blueprint in blueprint.line_blueprints:
            result = super().generate(
                line_blueprint,
                start_time_seconds=0.0,
                provider_name=provider_name,
            )

            if not result.success or result.audio_track is None:
                return result.model_copy(
                    update={"scene_number": blueprint.scene_number}
                )

            results.append(result)

        files = [
            str(result.audio_track.source_file)
            for result in results
            if result.audio_track
        ]
        dry_run = any(is_dry_run_placeholder(file) for file in files)
        # A scene that is ONE named line has nothing to join: its own file is the scene's file.
        single_line = len(files) == 1
        joined_file = (
            files[0]
            if single_line
            # A dry run makes placeholder "files" that no tool can open: keep a placeholder, join nothing.
            else (
                files[0].replace("dry-run://", "dry-run://cast_")
                if dry_run
                else str(
                    Path(files[0]).with_name(
                        f"scene_{blueprint.scene_number:03d}_cast_{uuid.uuid4().hex[:8]}"
                        f"{Path(files[0]).suffix}"
                    )
                )
            )
        )

        if not dry_run and not single_line:
            try:
                join_audio_files(files, joined_file)
            except (RuntimeError, ValueError) as error:
                return results[0].model_copy(
                    update={
                        "success": False,
                        "scene_number": blueprint.scene_number,
                        "status": VoiceGenerationStatus.FAILED,
                        "output_file": None,
                        "audio_track": None,
                        "warnings": [*results[0].warnings, str(error)],
                    }
                )

        spoken_seconds = sum(
            float(result.audio_track.duration_seconds)
            for result in results
            if result.audio_track
        )
        total_seconds = spoken_seconds + LINE_GAP_SECONDS * (len(results) - 1)
        measured = None if dry_run else self._detect_duration_seconds(Path(joined_file))

        if measured is not None and measured > 0.0:
            total_seconds = measured

        first_track = results[0].audio_track
        assert first_track is not None
        speakers = [
            str(line.metadata.get("speaker", "Narrator"))
            for line in blueprint.line_blueprints
        ]
        track = first_track.model_copy(
            update={
                "source_file": joined_file,
                "start_time_seconds": start_time_seconds,
                "duration_seconds": total_seconds,
                "metadata": {
                    **first_track.metadata,
                    "scene_number": blueprint.scene_number,
                    "voice_lines": speakers,
                    "measured_duration_seconds": total_seconds,
                },
            }
        )

        # Subtitle timing and clip sizing read the scene blueprint's own best-known duration.
        blueprint.estimated_speech_duration_seconds = total_seconds
        blueprint.output_file = joined_file
        blueprint.status = VoiceBlueprintResolutionStatus.GENERATED

        warnings = list(
            dict.fromkeys(warning for result in results for warning in result.warnings)
        )

        return VoiceGenerationResult(
            success=True,
            scene_number=blueprint.scene_number,
            status=VoiceGenerationStatus.COMPLETED,
            provider=results[0].provider,
            output_file=joined_file,
            audio_track=track,
            attempts=sum(result.attempts for result in results),
            warnings=warnings,
            metadata={"voice_lines": speakers},
        )
