from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.models.final_export import FinalExportPackage
from src.models.final_export_validation import FinalExportValidationResult
from src.models.render_orchestration_result import (
    RenderOrchestrationResult,
)
from src.models.seo import SEOPackage
from src.models.thumbnail import ThumbnailArtifact
from src.services.final_export.final_export_packaging_service import (
    FinalExportPackagingService,
)
from src.services.final_export.final_export_validation_service import (
    FinalExportValidationService,
)


@dataclass(frozen=True, slots=True)
class FinalExportBuildResult:
    """One completed FinalExportPackage together with its validation report."""

    package: FinalExportPackage
    validation: FinalExportValidationResult


class FinalExportService:
    """
    Orchestrate the final export package pipeline.

    Unlike SEOPackageService and ThumbnailPackageService, this
    genuinely requires a successful render: the final video is the
    package's core deliverable, so a completed
    RenderOrchestrationResult is a hard prerequisite rather than an
    optional enhancement.
    """

    def __init__(
        self,
        *,
        export_root: str | Path,
        packaging_service: FinalExportPackagingService | None = None,
        validation_service: FinalExportValidationService | None = None,
    ) -> None:
        self.packaging_service = packaging_service or (
            FinalExportPackagingService(export_root=export_root)
        )

        self.validation_service = validation_service or FinalExportValidationService()

    def build(
        self,
        render_orchestration_result: RenderOrchestrationResult,
        *,
        project_id: str,
        resolution: str,
        frame_rate: int,
        seo_package: SEOPackage,
        thumbnail_artifact: ThumbnailArtifact,
    ) -> FinalExportBuildResult:
        """Build and validate one FinalExportPackage from a completed render."""

        if not render_orchestration_result.success:
            raise ValueError(
                "Final export requires a successful render orchestration " "result."
            )

        render_result = render_orchestration_result.render_result

        if render_result is None or not render_result.output_file:
            raise ValueError(
                "Final export requires a render result with an output file."
            )

        package = self.packaging_service.package(
            video_job_id=render_orchestration_result.job.id,
            project_id=project_id,
            final_video_source_path=render_result.output_file,
            resolution=resolution,
            frame_rate=frame_rate,
            duration_seconds=render_result.duration_seconds,
            seo_package=seo_package,
            thumbnail_artifact=thumbnail_artifact,
        )

        validation = self.validation_service.validate(package)

        return FinalExportBuildResult(package=package, validation=validation)
