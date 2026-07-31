from __future__ import annotations

import time

from src.models.render_result import RenderResult
from src.pipeline.base_stage import BasePipelineStage
from src.pipeline.pipeline_stage import (
    PipelineStageName,
    PipelineStageStatus,
)
from src.pipeline.stage_context import StageContext
from src.pipeline.stage_result import StageResult
from src.services.render_service import RenderService


class RenderPipelineStage(BasePipelineStage):
    """
    Pipeline adapter for the existing RenderService.

    This class contains orchestration glue only. Rendering behavior
    remains owned by RenderService.

    The current RenderService is still the project's dry-run render
    abstraction. Real FFmpeg command planning and execution remain
    separate production services and will be integrated by a later
    render-execution adapter rather than being duplicated here.
    """

    def __init__(
        self,
        *,
        render_service: RenderService | None = None,
    ) -> None:
        self._render_service = (
            render_service
            or RenderService()
        )

    @property
    def stage_name(
        self,
    ) -> PipelineStageName:
        """Return the pipeline identifier for this adapter."""

        return PipelineStageName.RENDER

    def execute(
        self,
        context: StageContext,
    ) -> StageResult:
        """
        Render the VideoJob's prepared video timeline.

        Expected exceptions from invalid orchestration state are returned
        as failed StageResults. Unexpected exceptions from the underlying
        service are intentionally allowed to cross this adapter boundary
        so RenderOrchestratorService can normalize them consistently.
        """

        start_time = time.perf_counter()

        timeline = (
            context.job.video_timeline
        )

        if timeline is None:
            return self._failed_result(
                started_at=start_time,
                error_message=(
                    "Render stage requires "
                    "VideoJob.video_timeline."
                ),
            )

        if not (
            timeline.items
            or timeline.clips
        ):
            return self._failed_result(
                started_at=start_time,
                error_message=(
                    "Render stage requires a "
                    "non-empty video timeline."
                ),
            )

        render_result = (
            self._render_service.render(
                timeline
            )
        )

        context.job.render_result = (
            render_result
        )

        return self._stage_result_from_render(
            render_result=render_result,
            started_at=start_time,
        )

    def _stage_result_from_render(
        self,
        *,
        render_result: RenderResult,
        started_at: float,
    ) -> StageResult:
        """
        Translate the existing provider-independent RenderResult into the
        generic pipeline StageResult contract.
        """

        duration_seconds = (
            time.perf_counter()
            - started_at
        )

        metadata: dict[
            str,
            object,
        ] = {
            "render_engine": (
                render_result
                .render_engine
            ),
            "output_file": (
                render_result
                .output_file
            ),
            "render_time_seconds": (
                render_result
                .render_time_seconds
            ),
            "render_duration_seconds": (
                render_result
                .duration_seconds
            ),
        }

        if render_result.success:
            return StageResult(
                stage=self.stage_name,
                status=(
                    PipelineStageStatus
                    .COMPLETED
                ),
                duration_seconds=(
                    duration_seconds
                ),
                progress_percent=100,
                warnings=list(
                    render_result.warnings
                ),
                errors=[],
                metadata=metadata,
            )

        error_message = (
            render_result.error_message
            or (
                "Render service returned "
                "an unsuccessful result."
            )
        )

        return StageResult(
            stage=self.stage_name,
            status=(
                PipelineStageStatus.FAILED
            ),
            duration_seconds=(
                duration_seconds
            ),
            progress_percent=100,
            warnings=list(
                render_result.warnings
            ),
            errors=[
                error_message,
            ],
            metadata=metadata,
        )

    def _failed_result(
        self,
        *,
        started_at: float,
        error_message: str,
    ) -> StageResult:
        """Create a normalized precondition failure."""

        return StageResult(
            stage=self.stage_name,
            status=(
                PipelineStageStatus.FAILED
            ),
            duration_seconds=(
                time.perf_counter()
                - started_at
            ),
            progress_percent=100,
            errors=[
                error_message,
            ],
            metadata={
                "render_engine": None,
                "output_file": None,
            },
        )