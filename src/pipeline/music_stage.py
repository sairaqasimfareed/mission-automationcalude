from __future__ import annotations

import time

from src.models.audio_timeline import AudioTimeline
from src.models.video_timeline_item import VideoTimelineItem
from src.pipeline.base_stage import BasePipelineStage
from src.pipeline.pipeline_stage import PipelineStageName, PipelineStageStatus
from src.pipeline.stage_context import StageContext
from src.pipeline.stage_result import StageResult
from src.services.music_generation_service import MusicGenerationService


class MusicPipelineStage(BasePipelineStage):
    """
    Pipeline adapter for provider-independent background-music
    generation.

    Runs after TimelinePipelineStage: the resolved music instruction
    it needs (genre-resolved preset, volume, fade, ducking) lives on
    each timeline item's editing_blueprint, which TimelinePipelineStage
    is what actually builds. Background music is one continuous track
    for the whole video rather than per-scene, so this stage only
    needs one enabled instruction - every scene sharing the same genre
    profile resolves to the same preset, so the first one found is
    used, sized to the full timeline duration.

    Unlike voice, a missing or failed music track does not fail the
    render: a video without background music is still a valid,
    deliverable video. Every failure path here returns COMPLETED with
    a warning, never FAILED.
    """

    def __init__(
        self,
        *,
        generation_service: MusicGenerationService,
        provider_name: str | None = None,
    ) -> None:
        self._generation_service = generation_service

        normalized_provider = (
            provider_name.strip() if provider_name is not None else None
        )

        self._provider_name = normalized_provider or None

    @property
    def stage_name(self) -> PipelineStageName:
        return PipelineStageName.BACKGROUND_MUSIC

    def execute(self, context: StageContext) -> StageResult:
        started_at = time.perf_counter()

        timeline = context.job.video_timeline

        if timeline is None:
            return self._skipped_result(
                started_at=started_at,
                warning="Music stage requires a built video timeline.",
            )

        instruction_item = self._first_enabled_music_item(timeline.items)

        if instruction_item is None:
            return self._skipped_result(
                started_at=started_at,
                warning=None,
                metadata={"reason": "no_music_configured_for_genre"},
            )

        assert instruction_item.editing_blueprint is not None

        duration_seconds = timeline.calculate_duration()

        result = self._generation_service.generate(
            instruction_item.editing_blueprint.music,
            duration_seconds=duration_seconds,
            provider_name=self._provider_name,
        )

        if not result.success:
            message = (
                result.failure.message
                if result.failure is not None
                else "Music generation failed without failure details."
            )

            return self._skipped_result(
                started_at=started_at,
                warning=f"Background music was not generated: {message}",
                metadata={"reason": "generation_failed"},
            )

        assert result.audio_track is not None

        audio_timeline = context.job.audio_timeline or AudioTimeline()
        audio_timeline.tracks.append(result.audio_track)
        context.job.audio_timeline = audio_timeline

        return StageResult(
            stage=self.stage_name,
            status=PipelineStageStatus.COMPLETED,
            duration_seconds=time.perf_counter() - started_at,
            progress_percent=100,
            warnings=list(result.warnings),
            errors=[],
            metadata={
                "attached": True,
                "provider": result.provider,
                "output_file": result.output_file,
                "duration_seconds": duration_seconds,
            },
        )

    @staticmethod
    def _first_enabled_music_item(
        items: list[VideoTimelineItem],
    ) -> VideoTimelineItem | None:
        for item in sorted(items, key=lambda value: value.scene_number):
            if (
                item.editing_blueprint is not None
                and item.editing_blueprint.music.enabled
            ):
                return item

        return None

    def _skipped_result(
        self,
        *,
        started_at: float,
        warning: str | None,
        metadata: dict[str, object] | None = None,
    ) -> StageResult:
        """
        Build a non-fatal COMPLETED result for every "no music" path.

        Music is an enhancement, not a hard requirement - StageResult
        forbids errors on a COMPLETED status, so any failure here is
        surfaced only as a warning (or silently, when there was
        genuinely nothing to generate).
        """

        return StageResult(
            stage=self.stage_name,
            status=PipelineStageStatus.COMPLETED,
            duration_seconds=time.perf_counter() - started_at,
            progress_percent=100,
            warnings=[warning] if warning else [],
            errors=[],
            metadata={"attached": False, **(metadata or {})},
        )
