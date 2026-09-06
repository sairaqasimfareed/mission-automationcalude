from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.models.audio_track import AudioTrackType
from src.models.final_export import FinalExportPackage, FinalExportStatus
from src.models.final_export_validation import FinalExportValidationResult
from src.models.production_provenance import ProductionProvenance
from src.models.render_orchestration_result import (
    RenderOrchestrationResult,
)
from src.models.seo import SEOPackage
from src.models.thumbnail import ThumbnailArtifact
from src.models.video_job import VideoJob
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
        """
        Build and validate one FinalExportPackage from a completed render.

        Post-Script-Approval Production Plan, Phase 15: the resulting
        package's status is marked APPROVED only when validation finds
        no hard errors ("Mark project PUBLISH_READY only when hard QC
        gates pass"). A failing package is marked UNDER_REVIEW rather
        than REJECTED - REJECTED is reserved for a future explicit
        human rejection, matching how this codebase's other package
        status enums (SEOPackage, ThumbnailArtifact) already use the
        same four-state vocabulary.
        """

        if not render_orchestration_result.success:
            raise ValueError(
                "Final export requires a successful render orchestration " "result."
            )

        render_result = render_orchestration_result.render_result

        if render_result is None or not render_result.output_file:
            raise ValueError(
                "Final export requires a render result with an output file."
            )

        provenance = self._build_provenance(
            job=render_orchestration_result.job,
            render_engine=render_result.render_engine,
            render_exit_code=render_result.exit_code,
            render_ffmpeg_command=render_result.ffmpeg_command,
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
            provenance=provenance,
        )

        validation = self.validation_service.validate(package)

        final_status = (
            FinalExportStatus.APPROVED
            if validation.is_valid
            else FinalExportStatus.UNDER_REVIEW
        )

        package = package.model_copy(update={"status": final_status})

        self.packaging_service.rewrite_manifest(package)

        return FinalExportBuildResult(package=package, validation=validation)

    @staticmethod
    def _build_provenance(
        *,
        job: VideoJob,
        render_engine: str,
        render_exit_code: int | None,
        render_ffmpeg_command: list[str],
    ) -> ProductionProvenance:
        """
        Snapshot the exact production inputs this render was built
        from, straight off the already-persisted VideoJob and
        RenderResult - no re-derivation, no network/LLM calls.
        """

        script_lock = job.script_lock

        video_item_count = (
            len(job.video_timeline.items) if job.video_timeline is not None else 0
        )

        audio_tracks = (
            job.audio_timeline.tracks if job.audio_timeline is not None else []
        )

        voice_track_count = sum(
            1 for track in audio_tracks if track.track_type == AudioTrackType.VOICEOVER
        )

        return ProductionProvenance(
            script_lock_hash=(
                script_lock.script_content_hash if script_lock is not None else None
            ),
            script_version_number=(
                script_lock.script_version_number if script_lock is not None else None
            ),
            video_item_count=video_item_count,
            audio_track_count=len(audio_tracks),
            voice_track_count=voice_track_count,
            render_engine=render_engine,
            render_exit_code=render_exit_code,
            render_ffmpeg_command=list(render_ffmpeg_command),
        )
