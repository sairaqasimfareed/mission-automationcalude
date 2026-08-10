from __future__ import annotations

from typing import Any
from uuid import UUID

from src.models.project_specification import (
    ProjectSpecification,
)
from src.models.render_orchestration_result import (
    RenderOrchestrationResult,
)
from src.models.video_job import VideoJob
from src.services.content_pipeline import ContentPipeline
from src.services.project_specification_job_mapper import (
    ProjectSpecificationJobMapper,
)
from src.services.render_orchestrator_service import (
    RenderOrchestratorService,
)


class MissionApplicationService:
    """
    Application-level entry point for Mission Automation execution.

    The service composes existing domain and orchestration services
    without duplicating their responsibilities.

    Fresh execution:
    ProjectSpecification
        -> ProjectSpecificationJobMapper
        -> ContentPipeline
        -> RenderOrchestratorService

    Resume execution:
    existing VideoJob
        -> RenderOrchestratorService

    Mapping validation remains delegated to
    ProjectSpecificationJobMapper.

    Content generation remains delegated to ContentPipeline.

    Render execution, checkpoint loading, resume planning, user-input
    consumption, retry behavior, and normalized execution results remain
    delegated to RenderOrchestratorService.
    """

    def __init__(
        self,
        *,
        job_mapper: ProjectSpecificationJobMapper,
        content_pipeline: ContentPipeline,
        render_orchestrator: RenderOrchestratorService,
    ) -> None:
        self._job_mapper = job_mapper
        self._content_pipeline = content_pipeline
        self._render_orchestrator = render_orchestrator

    @property
    def job_mapper(
        self,
    ) -> ProjectSpecificationJobMapper:
        """Return the configured specification-to-job mapper."""

        return self._job_mapper

    @property
    def content_pipeline(
        self,
    ) -> ContentPipeline:
        """Return the configured core content pipeline."""

        return self._content_pipeline

    @property
    def render_orchestrator(
        self,
    ) -> RenderOrchestratorService:
        """Return the configured render orchestrator."""

        return self._render_orchestrator

    def execute(
        self,
        specification: ProjectSpecification,
        *,
        niche: str,
        dry_run: bool = False,
    ) -> RenderOrchestrationResult:
        """
        Execute a new Mission Automation project.

        A fresh VideoJob is created from the supplied project
        specification. The core content pipeline prepares research,
        script, originality analysis, and scenes before the job is
        passed to the existing render orchestration boundary.

        Mapper and content-pipeline exceptions intentionally propagate
        to the caller. Render-orchestration failures are already
        normalized by RenderOrchestratorService.
        """

        job = self._job_mapper.map(
            specification,
            niche=niche,
        )

        prepared_job = (
            self._content_pipeline.run(
                job
            )
        )

        return self._render_orchestrator.execute(
            prepared_job,
            dry_run=dry_run,
        )

    def resume(
        self,
        job: VideoJob,
        *,
        checkpoint_id: UUID | None = None,
        user_input: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> RenderOrchestrationResult:
        """
        Resume execution for an existing VideoJob.

        Resume deliberately bypasses ProjectSpecification mapping and
        ContentPipeline execution because the supplied VideoJob already
        represents persisted workflow state.

        Checkpoint selection, resume planning, stale-resume protection,
        user-input consumption, and stage execution remain delegated to
        RenderOrchestratorService.
        """

        return self._render_orchestrator.execute(
            job,
            dry_run=dry_run,
            checkpoint_id=checkpoint_id,
            user_input=user_input,
        )