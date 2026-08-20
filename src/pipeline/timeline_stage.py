from __future__ import annotations

import time

from src.models.editing_directives import (
    SceneEditingDirectives,
)
from src.models.genre_timeline_pipeline import (
    GenreTimelinePipelineResult,
)
from src.pipeline.base_stage import BasePipelineStage
from src.pipeline.pipeline_stage import (
    PipelineStageName,
    PipelineStageStatus,
)
from src.pipeline.stage_context import StageContext
from src.pipeline.stage_result import StageResult
from src.services.genre_timeline_pipeline_service import (
    GenreTimelinePipelineService,
)


class TimelinePipelineStage(BasePipelineStage):
    """
    Pipeline adapter for GenreTimelinePipelineService.

    The adapter contains orchestration glue only. Genre-aware editing
    directives, blueprint resolution, timeline construction, and
    validation remain owned by GenreTimelinePipelineService.

    The underlying service is injected explicitly because it owns
    required directive-generation and directive-resolution
    dependencies.

    A genre ID is also supplied explicitly because VideoJob currently
    stores a niche but does not define a canonical genre-profile ID.
    """

    def __init__(
        self,
        *,
        genre_id: str,
        timeline_service: GenreTimelinePipelineService,
        overrides_by_scene: dict[int, SceneEditingDirectives] | None = None,
        output_resolution: str = "1920x1080",
        frame_rate: int = 30,
        warn_on_blueprint_fallbacks: bool = True,
    ) -> None:
        normalized_genre_id = genre_id.strip().lower()

        if not normalized_genre_id:
            raise ValueError("Timeline pipeline stage requires " "a genre ID.")

        cleaned_resolution = output_resolution.strip()

        if not cleaned_resolution:
            raise ValueError(
                "Timeline pipeline stage requires " "an output resolution."
            )

        if frame_rate <= 0:
            raise ValueError("Timeline pipeline stage frame rate " "must be positive.")

        self._genre_id = normalized_genre_id

        self._timeline_service = timeline_service

        self._overrides_by_scene = dict(overrides_by_scene or {})

        self._output_resolution = cleaned_resolution

        self._frame_rate = frame_rate

        self._warn_on_blueprint_fallbacks = warn_on_blueprint_fallbacks

    @property
    def stage_name(
        self,
    ) -> PipelineStageName:
        """Return the internal pipeline identifier."""

        return PipelineStageName.VIDEO_TIMELINE

    @property
    def genre_id(
        self,
    ) -> str:
        """Return the normalized genre-profile identifier."""

        return self._genre_id

    def execute(
        self,
        context: StageContext,
    ) -> StageResult:
        """
        Build and validate the VideoJob's genre-aware video timeline.

        Missing upstream orchestration state is returned as a failed
        StageResult.

        Exceptions raised by the underlying timeline service propagate
        so RenderOrchestratorService can normalize unexpected service
        failures consistently.
        """

        start_time = time.perf_counter()

        if not context.job.scenes:
            return self._failed_result(
                started_at=start_time,
                error_message=("Timeline stage requires " "planned scenes."),
            )

        if not context.job.video_clips:
            return self._failed_result(
                started_at=start_time,
                error_message=("Timeline stage requires " "ready video clips."),
            )

        pipeline_result = self._timeline_service.build(
            scenes=list(context.job.scenes),
            clips=list(context.job.video_clips),
            genre_id=(self._genre_id),
            overrides_by_scene=dict(self._overrides_by_scene),
            output_resolution=(self._output_resolution),
            frame_rate=(self._frame_rate),
            warn_on_blueprint_fallbacks=(self._warn_on_blueprint_fallbacks),
        )

        return self._translate_result(
            context=context,
            pipeline_result=(pipeline_result),
            started_at=start_time,
        )

    def _translate_result(
        self,
        *,
        context: StageContext,
        pipeline_result: GenreTimelinePipelineResult,
        started_at: float,
    ) -> StageResult:
        """
        Translate GenreTimelinePipelineResult into the generic
        StageResult contract.
        """

        elapsed_seconds = time.perf_counter() - started_at

        metadata: dict[
            str,
            object,
        ] = {
            "genre_id": (pipeline_result.requested_genre_id),
            "genre_timeline_status": (pipeline_result.status.value),
            "render_ready": (pipeline_result.is_render_ready),
            "scene_count": (pipeline_result.scene_count),
            "fallback_count": (pipeline_result.fallback_count),
            "timeline_duration_seconds": (
                pipeline_result.timeline.calculate_duration()
            ),
            "output_resolution": (pipeline_result.timeline.output_resolution),
            "frame_rate": (pipeline_result.timeline.frame_rate),
            "validation_issue_count": (pipeline_result.validation.issue_count),
        }

        if pipeline_result.is_render_ready:
            context.job.video_timeline = pipeline_result.timeline

            return StageResult(
                stage=self.stage_name,
                status=(PipelineStageStatus.COMPLETED),
                duration_seconds=(elapsed_seconds),
                progress_percent=100,
                warnings=list(pipeline_result.warnings),
                errors=[],
                metadata=metadata,
            )

        errors = self._validation_errors(pipeline_result)

        if not errors:
            errors = [
                (
                    "Genre timeline pipeline "
                    "did not produce a "
                    "render-ready timeline."
                ),
            ]

        return StageResult(
            stage=self.stage_name,
            status=(PipelineStageStatus.FAILED),
            duration_seconds=(elapsed_seconds),
            progress_percent=100,
            warnings=list(pipeline_result.warnings),
            errors=errors,
            metadata=metadata,
        )

    @staticmethod
    def _validation_errors(
        pipeline_result: GenreTimelinePipelineResult,
    ) -> list[str]:
        """Return unique timeline-validation error messages."""

        errors: list[str] = []

        for issue in pipeline_result.validation.errors:
            message = issue.message.strip()

            if message and message not in errors:
                errors.append(message)

        return errors

    def _failed_result(
        self,
        *,
        started_at: float,
        error_message: str,
    ) -> StageResult:
        """Create a normalized timeline-stage precondition failure."""

        return StageResult(
            stage=self.stage_name,
            status=(PipelineStageStatus.FAILED),
            duration_seconds=(time.perf_counter() - started_at),
            progress_percent=100,
            errors=[
                error_message,
            ],
            metadata={
                "genre_id": (self._genre_id),
                "render_ready": False,
            },
        )
