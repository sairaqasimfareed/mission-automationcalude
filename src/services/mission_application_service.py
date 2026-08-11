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
from src.models.seo import SEOPackage
from src.models.thumbnail import ThumbnailArtifact, ThumbnailTextPosition
from src.models.video_job import VideoJob
from src.services.content_pipeline import (
    ContentPipeline,
)
from src.services.final_export.final_export_service import (
    FinalExportBuildResult,
    FinalExportService,
)
from src.services.project_render_runtime_factory import (
    ProjectRenderRuntimeFactory,
)
from src.services.project_specification_job_mapper import (
    ProjectSpecificationJobMapper,
)
from src.services.seo.seo_context_builder import SEOContextBuilder
from src.services.seo.seo_package_service import (
    SEOPackageBuildResult,
    SEOPackageService,
)
from src.services.thumbnail.thumbnail_package_service import (
    ThumbnailPackageBuildResult,
    ThumbnailPackageService,
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

    SEO package generation (generate_seo_package) is a separate,
    optional capability. It requires only research, script, and scene
    content - all of which already exist once ContentPipeline has run
    - so it does not depend on render execution, does not mutate
    VideoJob, and does not interact with checkpoint/resume state.
    """

    def __init__(
        self,
        *,
        job_mapper: ProjectSpecificationJobMapper,
        content_pipeline: ContentPipeline,
        render_runtime_factory: ProjectRenderRuntimeFactory,
        seo_package_service: SEOPackageService | None = None,
        thumbnail_package_service: ThumbnailPackageService | None = None,
        final_export_service: FinalExportService | None = None,
    ) -> None:
        self._job_mapper = job_mapper
        self._content_pipeline = content_pipeline
        self._render_runtime_factory = render_runtime_factory
        self._seo_package_service = seo_package_service
        self._thumbnail_package_service = thumbnail_package_service
        self._final_export_service = final_export_service

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

    @property
    def seo_package_service(
        self,
    ) -> SEOPackageService | None:
        """Return the configured SEO package service, if any."""

        return self._seo_package_service

    def generate_seo_package(
        self,
        job: VideoJob,
        *,
        genre_id: str,
        target_audience: str,
        language_code: str = "en",
        title_candidate_count: int = 5,
        max_tags: int = 15,
        max_hashtags: int = 8,
    ) -> SEOPackageBuildResult:
        """
        Generate a validated SEOPackage for a job with an approved script.

        This does not require job.render_result to be set: SEO metadata
        only needs research, script and scene content. It can be called
        any time after ContentPipeline has produced an approved script,
        independent of whether or when render() has been executed.
        """

        if self._seo_package_service is None:
            raise ValueError(
                "SEO package generation requires a configured " "SEOPackageService."
            )

        return self._seo_package_service.build(
            job,
            genre_id=genre_id,
            target_audience=target_audience,
            language_code=language_code,
            title_candidate_count=title_candidate_count,
            max_tags=max_tags,
            max_hashtags=max_hashtags,
        )

    @property
    def thumbnail_package_service(
        self,
    ) -> ThumbnailPackageService | None:
        """Return the configured thumbnail package service, if any."""

        return self._thumbnail_package_service

    def generate_thumbnail(
        self,
        job: VideoJob,
        *,
        genre_id: str,
        target_audience: str,
        project_id: str,
        language_code: str = "en",
        concept_count: int = 3,
        selected_seo_title: str | None = None,
        hook_text_position: ThumbnailTextPosition = ThumbnailTextPosition.BOTTOM,
    ) -> ThumbnailPackageBuildResult:
        """
        Generate a validated ThumbnailArtifact for a job with an
        approved script.

        Like generate_seo_package, this does not require
        job.render_result to be set and does not mutate VideoJob or
        interact with checkpoint/resume state. It builds its own
        SEOContext from the job rather than requiring the caller to
        have one already, so it can be called independently of
        generate_seo_package.
        """

        if self._thumbnail_package_service is None:
            raise ValueError(
                "Thumbnail generation requires a configured " "ThumbnailPackageService."
            )

        context = SEOContextBuilder().build(
            job,
            genre_id=genre_id,
            target_audience=target_audience,
            language_code=language_code,
        )

        return self._thumbnail_package_service.build(
            context,
            project_id=project_id,
            concept_count=concept_count,
            selected_seo_title=selected_seo_title,
            hook_text_position=hook_text_position,
        )

    @property
    def final_export_service(
        self,
    ) -> FinalExportService | None:
        """Return the configured final export service, if any."""

        return self._final_export_service

    def export_final_package(
        self,
        render_orchestration_result: RenderOrchestrationResult,
        *,
        project_id: str,
        resolution: str,
        frame_rate: int,
        seo_package: SEOPackage,
        thumbnail_artifact: ThumbnailArtifact,
    ) -> FinalExportBuildResult:
        """
        Build a validated FinalExportPackage from a completed render.

        Unlike generate_seo_package and generate_thumbnail, this
        genuinely requires a successful render_orchestration_result:
        the final video is the package's core deliverable. Call
        execute()/resume(), generate_seo_package(), and
        generate_thumbnail() first and pass their results in here.
        """

        if self._final_export_service is None:
            raise ValueError("Final export requires a configured FinalExportService.")

        return self._final_export_service.build(
            render_orchestration_result,
            project_id=project_id,
            resolution=resolution,
            frame_rate=frame_rate,
            seo_package=seo_package,
            thumbnail_artifact=thumbnail_artifact,
        )

    def execute(
        self,
        specification: ProjectSpecification,
        *,
        niche: str,
        genre_id: str,
        language: str = "English",
        language_code: str = "en",
        voice_provider_name: str | None = None,
        overrides_by_scene: dict[int, SceneEditingDirectives] | None = None,
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

        prepared_job = self._content_pipeline.run(job)

        render_orchestrator = self._render_runtime_factory.build(
            job=prepared_job,
            genre_id=genre_id,
            language=language,
            language_code=language_code,
            voice_provider_name=(voice_provider_name),
            overrides_by_scene=(overrides_by_scene),
            output_resolution=(output_resolution),
            frame_rate=frame_rate,
            warn_on_blueprint_fallbacks=(warn_on_blueprint_fallbacks),
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
        overrides_by_scene: dict[int, SceneEditingDirectives] | None = None,
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

        render_orchestrator = self._render_runtime_factory.build(
            job=job,
            genre_id=genre_id,
            language=language,
            language_code=language_code,
            voice_provider_name=(voice_provider_name),
            overrides_by_scene=(overrides_by_scene),
            output_resolution=(output_resolution),
            frame_rate=frame_rate,
            warn_on_blueprint_fallbacks=(warn_on_blueprint_fallbacks),
        )

        return render_orchestrator.execute(
            job,
            dry_run=dry_run,
            checkpoint_id=checkpoint_id,
            user_input=user_input,
        )
