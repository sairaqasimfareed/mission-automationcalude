from __future__ import annotations

from uuid import UUID

from src.models.final_export import FinalExportPackage
from src.models.render_orchestration_result import RenderOrchestrationResult
from src.models.seo import SEOPackage
from src.models.thumbnail import ThumbnailArtifact
from src.models.video_job import VideoJob


class InMemoryJobStore:
    """
    Process-lifetime registry of VideoJobs created through the desktop
    UI.

    This is deliberately not durable persistence. It exists only so
    the dashboard can show projects created in the current app
    session: PipelineCheckpointStorageService.list_job_ids() only
    reflects jobs that have reached the render/checkpoint stage. Jobs
    are lost when the app closes.
    """

    def __init__(self) -> None:
        self._jobs: dict[UUID, VideoJob] = {}
        self._seo_packages: dict[UUID, SEOPackage] = {}
        self._thumbnails: dict[UUID, ThumbnailArtifact] = {}
        self._render_results: dict[UUID, RenderOrchestrationResult] = {}
        self._final_exports: dict[UUID, FinalExportPackage] = {}

    def add(self, job: VideoJob) -> None:
        self._jobs[job.id] = job

    def get(self, job_id: UUID) -> VideoJob | None:
        return self._jobs.get(job_id)

    def list_all(self) -> list[VideoJob]:
        return sorted(
            self._jobs.values(),
            key=lambda job: job.created_at,
            reverse=True,
        )

    def set_seo_package(self, job_id: UUID, seo_package: SEOPackage) -> None:
        self._seo_packages[job_id] = seo_package

    def get_seo_package(self, job_id: UUID) -> SEOPackage | None:
        return self._seo_packages.get(job_id)

    def set_thumbnail(self, job_id: UUID, thumbnail: ThumbnailArtifact) -> None:
        self._thumbnails[job_id] = thumbnail

    def get_thumbnail(self, job_id: UUID) -> ThumbnailArtifact | None:
        return self._thumbnails.get(job_id)

    def set_render_result(
        self,
        job_id: UUID,
        render_result: RenderOrchestrationResult,
    ) -> None:
        self._render_results[job_id] = render_result

    def get_render_result(self, job_id: UUID) -> RenderOrchestrationResult | None:
        return self._render_results.get(job_id)

    def set_final_export(
        self,
        job_id: UUID,
        final_export: FinalExportPackage,
    ) -> None:
        self._final_exports[job_id] = final_export

    def get_final_export(self, job_id: UUID) -> FinalExportPackage | None:
        return self._final_exports.get(job_id)
