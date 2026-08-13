from __future__ import annotations

import time

from src.models.audio_timeline import AudioTimeline
from src.models.editing_directives import DirectiveTimingMode
from src.models.resolved_editing_blueprint import ResolvedSoundEffectInstruction
from src.models.video_timeline_item import VideoTimelineItem
from src.pipeline.base_stage import BasePipelineStage
from src.pipeline.pipeline_stage import PipelineStageName, PipelineStageStatus
from src.pipeline.stage_context import StageContext
from src.pipeline.stage_result import StageResult
from src.services.sound_effect_generation_service import (
    SoundEffectGenerationService,
)


class SoundEffectPipelineStage(BasePipelineStage):
    """
    Pipeline adapter for provider-independent sound-effect generation.

    Runs after TimelinePipelineStage, for the same reason
    MusicPipelineStage does: each scene's resolved sound-effect cues
    live on VideoTimelineItem.editing_blueprint. Unlike music, sound
    effects are per-scene and there can be several per scene, each
    placed at its own cue point (scene start/middle/end, or an
    absolute offset) - resolved here into an absolute timeline
    position using the scene's actual start_time_seconds.

    Sound effects are an enhancement like music: a failed cue is
    skipped with a warning rather than failing the whole stage.
    """

    def __init__(
        self,
        *,
        generation_service: SoundEffectGenerationService,
        provider_name: str | None = None,
    ) -> None:
        self._generation_service = generation_service

        normalized_provider = (
            provider_name.strip() if provider_name is not None else None
        )

        self._provider_name = normalized_provider or None

    @property
    def stage_name(self) -> PipelineStageName:
        return PipelineStageName.SOUND_EFFECTS

    def execute(self, context: StageContext) -> StageResult:
        started_at = time.perf_counter()

        timeline = context.job.video_timeline

        if timeline is None:
            return StageResult(
                stage=self.stage_name,
                status=PipelineStageStatus.COMPLETED,
                duration_seconds=time.perf_counter() - started_at,
                progress_percent=100,
                warnings=["Sound-effect stage requires a built video timeline."],
                errors=[],
                metadata={"attached_count": 0},
            )

        audio_timeline = context.job.audio_timeline or AudioTimeline()
        warnings: list[str] = []
        attached_count = 0

        for item in sorted(timeline.items, key=lambda value: value.scene_number):
            if item.editing_blueprint is None:
                continue

            for cue in item.editing_blueprint.sound_effects:
                if not cue.enabled:
                    continue

                start_time_seconds = self._resolve_start_time(item=item, cue=cue)

                result = self._generation_service.generate(
                    cue,
                    scene_number=item.scene_number,
                    start_time_seconds=start_time_seconds,
                    provider_name=self._provider_name,
                )

                if not result.success:
                    message = (
                        result.failure.message
                        if result.failure is not None
                        else "Sound-effect generation failed without details."
                    )

                    warnings.append(
                        f"Scene {item.scene_number} sound effect was not "
                        f"generated: {message}"
                    )

                    continue

                assert result.audio_track is not None

                audio_timeline.tracks.append(result.audio_track)
                attached_count += 1

        context.job.audio_timeline = audio_timeline

        return StageResult(
            stage=self.stage_name,
            status=PipelineStageStatus.COMPLETED,
            duration_seconds=time.perf_counter() - started_at,
            progress_percent=100,
            warnings=warnings,
            errors=[],
            metadata={"attached_count": attached_count},
        )

    @staticmethod
    def _resolve_start_time(
        *,
        item: VideoTimelineItem,
        cue: ResolvedSoundEffectInstruction,
    ) -> float:
        """Resolve one cue's absolute timeline position."""

        scene_duration = max(item.end_time_seconds - item.start_time_seconds, 0.0)

        if cue.relative_position_percent is not None:
            offset = scene_duration * (cue.relative_position_percent / 100.0)
        elif cue.timing_mode == DirectiveTimingMode.SCENE_START:
            offset = 0.0
        elif cue.timing_mode == DirectiveTimingMode.SCENE_MIDDLE:
            offset = scene_duration / 2.0
        elif cue.timing_mode == DirectiveTimingMode.SCENE_END:
            offset = scene_duration
        else:
            offset = cue.start_offset_seconds

        clamped_offset = min(max(offset, 0.0), scene_duration)

        return item.start_time_seconds + clamped_offset
