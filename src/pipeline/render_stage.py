from __future__ import annotations

import time

from src.models.render_result import RenderResult
from src.models.resolved_voice_blueprint import (
    ResolvedVoiceBlueprint,
)
from src.pipeline.base_stage import BasePipelineStage
from src.pipeline.pipeline_stage import (
    PipelineStageName,
    PipelineStageStatus,
)
from src.pipeline.stage_context import StageContext
from src.pipeline.stage_result import StageResult
from src.services.production_render_service import (
    ProductionRenderService,
)
from src.services.render_service import RenderService


class RenderPipelineStage(BasePipelineStage):
    """
    Pipeline adapter for render execution.

    The stage remains orchestration glue only.

    When a ProductionRenderService is supplied, the stage executes the
    prepared VideoJob through the real FFmpeg production render boundary.

    When no production renderer is supplied, the existing RenderService
    path remains available for backward compatibility with legacy and
    isolated dry-run workflows.
    """

    def __init__(
        self,
        *,
        render_service: RenderService | None = None,
        production_render_service: ProductionRenderService | None = None,
        voice_blueprints: list[ResolvedVoiceBlueprint] | None = None,
    ) -> None:
        if production_render_service is not None and not voice_blueprints:
            raise ValueError(
                "Production render stage requires " "resolved voice blueprints."
            )

        self._render_service = render_service or RenderService()

        self._production_render_service = production_render_service

        self._voice_blueprints = list(voice_blueprints or [])

    @property
    def stage_name(
        self,
    ) -> PipelineStageName:
        """Return the pipeline identifier for this adapter."""

        return PipelineStageName.RENDER

    @property
    def production_render_enabled(
        self,
    ) -> bool:
        """Return whether real production rendering is configured."""

        return self._production_render_service is not None

    def execute(
        self,
        context: StageContext,
    ) -> StageResult:
        """
        Render the VideoJob's prepared timelines.

        Expected orchestration-state errors are normalized into failed
        StageResults.

        Unexpected renderer exceptions intentionally cross this adapter
        boundary so RenderOrchestratorService can apply its existing
        exception-normalization policy.
        """

        start_time = time.perf_counter()

        timeline = context.job.video_timeline

        if timeline is None:
            return self._failed_result(
                started_at=start_time,
                error_message=("Render stage requires " "VideoJob.video_timeline."),
            )

        if not (timeline.items or timeline.clips):
            return self._failed_result(
                started_at=start_time,
                error_message=("Render stage requires a " "non-empty video timeline."),
            )

        if self.production_render_enabled:
            render_result = self._execute_production_render(
                context=context,
            )
        else:
            render_result = self._render_service.render(timeline)

        context.job.render_result = render_result

        return self._stage_result_from_render(
            render_result=render_result,
            started_at=start_time,
        )

    def _execute_production_render(
        self,
        *,
        context: StageContext,
    ) -> RenderResult:
        """Execute the real production rendering boundary."""

        production_render_service = self._production_render_service

        if production_render_service is None:
            raise RuntimeError("Production render service " "is not configured.")

        video_timeline = context.job.video_timeline

        if video_timeline is None:
            raise RuntimeError("Production render requires " "VideoJob.video_timeline.")

        audio_timeline = context.job.audio_timeline

        if audio_timeline is None:
            raise ValueError(
                "Production render stage requires " "VideoJob.audio_timeline."
            )

        if not self._voice_blueprints:
            raise ValueError(
                "Production render stage requires " "resolved voice blueprints."
            )

        progress_callback = context.services.get("progress_callback")

        return production_render_service.render(
            video_timeline=video_timeline,
            audio_timeline=audio_timeline,
            voice_blueprints=(self._voice_blueprints),
            progress_callback=progress_callback,
        )

    def _stage_result_from_render(
        self,
        *,
        render_result: RenderResult,
        started_at: float,
    ) -> StageResult:
        """
        Translate the provider-independent RenderResult into the generic
        pipeline StageResult contract.
        """

        duration_seconds = time.perf_counter() - started_at

        metadata: dict[
            str,
            object,
        ] = {
            "render_engine": (render_result.render_engine),
            "output_file": (render_result.output_file),
            "render_time_seconds": (render_result.render_time_seconds),
            "render_duration_seconds": (render_result.duration_seconds),
            "production_render": (self.production_render_enabled),
        }

        if render_result.success:
            return StageResult(
                stage=self.stage_name,
                status=(PipelineStageStatus.COMPLETED),
                duration_seconds=(duration_seconds),
                progress_percent=100,
                warnings=list(render_result.warnings),
                errors=[],
                metadata=metadata,
            )

        error_message = render_result.error_message or (
            "Render service returned " "an unsuccessful result."
        )

        return StageResult(
            stage=self.stage_name,
            status=(PipelineStageStatus.FAILED),
            duration_seconds=(duration_seconds),
            progress_percent=100,
            warnings=list(render_result.warnings),
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
            status=(PipelineStageStatus.FAILED),
            duration_seconds=(time.perf_counter() - started_at),
            progress_percent=100,
            errors=[
                error_message,
            ],
            metadata={
                "render_engine": None,
                "output_file": None,
                "production_render": (self.production_render_enabled),
            },
        )
