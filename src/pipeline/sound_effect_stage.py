from __future__ import annotations

import time
from collections import Counter

from src.models.audio_timeline import AudioTimeline
from src.models.audio_track import AudioTrackType
from src.models.editing_directives import DirectiveTimingMode
from src.models.resolved_editing_blueprint import ResolvedSoundEffectInstruction
from src.models.video_timeline_item import VideoTimelineItem
from src.pipeline.base_stage import BasePipelineStage
from src.pipeline.pipeline_stage import PipelineStageName, PipelineStageStatus
from src.pipeline.stage_context import StageContext
from src.pipeline.stage_result import StageResult
from src.services.audio_cue_policy_service import AudioCuePolicyService
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
        cue_policy_service: AudioCuePolicyService | None = None,
    ) -> None:
        self._generation_service = generation_service

        normalized_provider = (
            provider_name.strip() if provider_name is not None else None
        )

        self._provider_name = normalized_provider or None
        # Post-Script-Approval Production Plan, Phase 10: "Prevent
        # duplicate/repetitive SFX and uncontrolled loudness
        # accumulation." Defaults to a real, active instance rather
        # than None - unlike Phase 8's technical-validation gate, this
        # check only ever appends warnings, it never blocks or changes
        # attached_count, so there is no existing behavior for a
        # default-off posture to protect.
        self._cue_policy_service = cue_policy_service or AudioCuePolicyService()

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
        skipped_existing_count = 0

        # Found via external audit: a full pipeline re-run
        # (resume_previous_pipeline=True + skip_completed_stages=False,
        # a real, reachable AdvancedSettings combination) re-executes
        # this stage even when it already completed, and this loop
        # used to append every cue unconditionally - silently
        # double-generating and double-attaching every SFX cue on
        # each re-run. This mirrors VoiceTimelineService's own
        # duplicate-scene guard: (scene_number, resolved start time)
        # is exactly what makes two cues "the same cue" here, since
        # start-time resolution is itself deterministic from the same
        # editing blueprint. A Counter, not a set, because two
        # genuinely distinct cues within one planning pass can
        # legitimately share a key (e.g. the repetitive-cue case
        # AudioCuePolicyService itself is meant to flag) - a snapshot
        # taken once, before this run attaches anything, so it only
        # ever matches tracks a *previous* run already created, never
        # a sibling cue from this same pass.
        remaining_existing_counts = Counter(
            (track.metadata.get("scene_number"), track.start_time_seconds)
            for track in audio_timeline.tracks
            if track.track_type == AudioTrackType.SOUND_EFFECT
        )

        for item in sorted(timeline.items, key=lambda value: value.scene_number):
            if item.editing_blueprint is None:
                continue

            for cue in item.editing_blueprint.sound_effects:
                if not cue.enabled:
                    continue

                start_time_seconds = self._resolve_start_time(item=item, cue=cue)

                cue_key = (item.scene_number, start_time_seconds)

                if remaining_existing_counts[cue_key] > 0:
                    remaining_existing_counts[cue_key] -= 1
                    skipped_existing_count += 1
                    continue

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

        if skipped_existing_count:
            warnings.append(
                f"Skipped {skipped_existing_count} sound-effect cue(s) "
                "already attached from a previous run."
            )

        context.job.audio_timeline = audio_timeline

        policy_result = self._cue_policy_service.evaluate(audio_timeline.tracks)

        for conflict in policy_result.conflicts:
            warnings.append(f"Audio cue policy: {conflict.detail}")

        return StageResult(
            stage=self.stage_name,
            status=PipelineStageStatus.COMPLETED,
            duration_seconds=time.perf_counter() - started_at,
            progress_percent=100,
            warnings=warnings,
            errors=[],
            metadata={
                "attached_count": attached_count,
                "skipped_existing_count": skipped_existing_count,
            },
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
