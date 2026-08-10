from __future__ import annotations

from typing import Any
from uuid import UUID

from src.models.editing_directives import (
    SceneEditingDirectives,
)
from src.models.project_specification import (
    ProjectSpecification,
)
from src.models.render_orchestration_result import (
    RenderOrchestrationResult,
)
from src.models.video_job import VideoJob
from src.services.content_pipeline import (
    ContentPipeline,
)
from src.services.project_render_runtime_factory import (
    ProjectRenderRuntimeFactory,
)
from src.services.project_specification_job_mapper import (
    ProjectSpecificationJobMapper,
)


class MissionApplicationService:
    """
    Application-level entry point for Mission Automation execution.

    Fresh execution:

    ProjectSpecification
        -> ProjectSpecificationJobMapper
        -> ContentPipeline
        -> ProjectRenderRuntimeFactory
        -> RenderOrchestratorService

    Resume execution:

    existing VideoJob
        -> ProjectRenderRuntimeFactory
        -> RenderOrchestratorService

    Mapping validation remains delegated to
    ProjectSpecificationJobMapper.

    Content generation remains delegated to ContentPipeline.

    Per-project voice-directive generation, voice-blueprint resolution,
    and render-stage composition remain delegated to
    ProjectRenderRuntimeFactory.

    Render execution, checkpoint loading, resume planning, user-input
    consumption, retry behavior, and normalized execution results remain
    delegated to RenderOrchestratorService.
    """

    def __init__(
        self,
        *,
        job_mapper: ProjectSpecificationJobMapper,
        content_pipeline: ContentPipeline,
        render_runtime_factory: ProjectRenderRuntimeFactory,
    ) -> None:
        self._job_mapper = job_mapper
        self._content_pipeline = content_pipeline
        self._render_runtime_factory = (
            render_runtime_factory
        )

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
    def render_runtime_factory(
        self,
    ) -> ProjectRenderRuntimeFactory:
        """
        Return the configured per-project render runtime factory.
        """

        return self._render_runtime_factory

    def execute(
        self,
        specification: ProjectSpecification,
        *,
        niche: str,
        genre_id: str,
        language: str = "English",
        language_code: str = "en",
        voice_provider_name: str | None = None,
        overrides_by_scene: (
            dict[int, SceneEditingDirectives]
            | None
        ) = None,
        output_resolution: str = "1920x1080",
        frame_rate: int = 30,
        warn_on_blueprint_fallbacks: bool = True,
        dry_run: bool = False,
    ) -> RenderOrchestrationResult:
        """
        Execute a new Mission Automation project.

        A fresh VideoJob is first mapped from the supplied project
        specification. The content pipeline prepares research, script,
        originality analysis, and scenes.

        A job-specific render orchestrator is then assembled from the
        prepared scene content and supplied runtime configuration before
        execution begins.

        Mapper, content-pipeline, and runtime-composition exceptions
        intentionally propagate to the caller.

        Render execution failures remain normalized by the existing
        RenderOrchestratorService.
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

        render_orchestrator = (
            self._render_runtime_factory.build(
                job=prepared_job,
                genre_id=genre_id,
                language=language,
                language_code=language_code,
                voice_provider_name=(
                    voice_provider_name
                ),
                overrides_by_scene=(
                    overrides_by_scene
                ),
                output_resolution=(
                    output_resolution
                ),
                frame_rate=frame_rate,
                warn_on_blueprint_fallbacks=(
                    warn_on_blueprint_fallbacks
                ),
            )
        )

        return render_orchestrator.execute(
            prepared_job,
            dry_run=dry_run,
        )

    def resume(
        self,
        job: VideoJob,
        *,
        genre_id: str,
        language: str = "English",
        language_code: str = "en",
        voice_provider_name: str | None = None,
        overrides_by_scene: (
            dict[int, SceneEditingDirectives]
            | None
        ) = None,
        output_resolution: str = "1920x1080",
        frame_rate: int = 30,
        warn_on_blueprint_fallbacks: bool = True,
        checkpoint_id: UUID | None = None,
        user_input: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> RenderOrchestrationResult:
        """
        Resume execution for an existing VideoJob.

        Resume deliberately bypasses ProjectSpecification mapping and
        ContentPipeline execution because the supplied VideoJob already
        represents persisted workflow state.

        A fresh orchestrator graph is reconstructed for the job using
        the same provider-independent runtime composition boundary.

        Checkpoint selection, resume planning, stale-resume protection,
        user-input consumption, skipped-stage behavior, retries, and
        execution remain delegated to RenderOrchestratorService.
        """

        render_orchestrator = (
            self._render_runtime_factory.build(
                job=job,
                genre_id=genre_id,
                language=language,
                language_code=language_code,
                voice_provider_name=(
                    voice_provider_name
                ),
                overrides_by_scene=(
                    overrides_by_scene
                ),
                output_resolution=(
                    output_resolution
                ),
                frame_rate=frame_rate,
                warn_on_blueprint_fallbacks=(
                    warn_on_blueprint_fallbacks
                ),
            )
        )

        return render_orchestrator.execute(
            job,
            dry_run=dry_run,
            checkpoint_id=checkpoint_id,
            user_input=user_input,
        )