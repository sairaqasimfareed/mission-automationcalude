from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.desktop.job_store import JobStore
from src.desktop.recovery_dialog import show_recoverable_error
from src.desktop.widgets import (
    button,
    card,
    muted,
    small_muted,
    status_label,
    subheading,
)
from src.models.final_export import FinalExportPackage
from src.models.seo import SEOPackage
from src.models.thumbnail import ThumbnailArtifact
from src.models.video_job import VideoJob
from src.services.final_export.final_export_service import FinalExportService
from src.services.seo.seo_context_builder import SEOContextBuilder
from src.services.seo.seo_package_service import SEOPackageService
from src.services.thumbnail.thumbnail_package_service import ThumbnailPackageService

_LEFT = Qt.AlignmentFlag.AlignLeft


class PackagingView(QWidget):
    """
    Packaging: SEO metadata, thumbnail, and final publish-ready export.

    Final export only becomes available once a render actually
    succeeds, and requires both an SEO package and a thumbnail -
    building it any earlier would package an incomplete or missing
    video.
    """

    def __init__(
        self,
        *,
        job_store: JobStore,
        seo_package_service: SEOPackageService,
        thumbnail_package_service: ThumbnailPackageService,
        final_export_service: FinalExportService,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__()

        self._job_store = job_store
        self._seo_package_service = seo_package_service
        self._thumbnail_package_service = thumbnail_package_service
        self._final_export_service = final_export_service
        self._on_change = on_change
        self._job_id: UUID | None = None

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        content_container = QWidget()
        self._layout = QVBoxLayout(content_container)
        self._layout.setContentsMargins(0, 12, 4, 0)
        self._layout.setSpacing(16)

        scroll_area.setWidget(content_container)
        outer_layout.addWidget(scroll_area)

    def set_job(self, job_id: UUID) -> None:
        self._job_id = job_id

    def refresh(self, job: VideoJob) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)

            if item is None:
                continue

            widget = item.widget()

            if widget is not None:
                widget.deleteLater()

        self._build_seo_card(job)
        self._build_thumbnail_card(job)
        self._build_final_export_card(job)

    def _build_seo_card(self, job: VideoJob) -> None:
        frame, layout = card("SEO package", icon_name="tag")

        assert self._job_id is not None

        seo_package = self._job_store.get_seo_package(self._job_id)

        script_approved = job.script is not None and job.script.status.value == (
            "approved"
        )

        if seo_package is not None:
            layout.addWidget(subheading(seo_package.selected_title or ""))
            layout.addWidget(muted(seo_package.description))
            layout.addWidget(small_muted(f"Tags: {', '.join(seo_package.tags)}"))
            layout.addWidget(small_muted(f"Hashtags: {' '.join(seo_package.hashtags)}"))
            layout.addWidget(
                small_muted(f"Version {seo_package.version_number}"),
            )

            self._build_script_lock_staleness_banner(
                layout,
                job=job,
                source_script_lock_hash=seo_package.source_script_lock_hash,
            )

            if script_approved:
                audience_input = QLineEdit("General audience")
                layout.addWidget(audience_input)

                regenerate_button = button("Regenerate SEO package", icon_name="tag")
                regenerate_button.clicked.connect(
                    lambda: self._handle_generate_seo(
                        audience_input.text(),
                        previous_package=seo_package,
                    ),
                )
                layout.addWidget(regenerate_button, alignment=_LEFT)
        elif script_approved:
            layout.addWidget(small_muted("Not generated yet."))

            audience_input = QLineEdit("General audience")
            layout.addWidget(audience_input)

            generate_button = button(
                "Generate SEO package", variant="primary", icon_name="tag"
            )
            generate_button.clicked.connect(
                lambda: self._handle_generate_seo(audience_input.text()),
            )
            layout.addWidget(generate_button, alignment=_LEFT)
        else:
            layout.addWidget(small_muted("Requires an approved script."))

        self._layout.addWidget(frame)

    def _build_thumbnail_card(self, job: VideoJob) -> None:
        frame, layout = card("Thumbnail", icon_name="image")

        assert self._job_id is not None

        thumbnail = self._job_store.get_thumbnail(self._job_id)

        script_approved = job.script is not None and job.script.status.value == (
            "approved"
        )

        if thumbnail is not None:
            layout.addWidget(subheading(thumbnail.concept.hook_text))
            layout.addWidget(
                small_muted(f"Source: {thumbnail.image_source_type.value}")
            )
            layout.addWidget(small_muted(f"File: {thumbnail.file_path}"))
            layout.addWidget(
                small_muted(f"Version {thumbnail.version_number}"),
            )

            self._build_script_lock_staleness_banner(
                layout,
                job=job,
                source_script_lock_hash=thumbnail.source_script_lock_hash,
            )

            if script_approved:
                audience_input = QLineEdit("General audience")
                layout.addWidget(audience_input)

                regenerate_button = button("Regenerate thumbnail", icon_name="image")
                regenerate_button.clicked.connect(
                    lambda: self._handle_generate_thumbnail(
                        audience_input.text(),
                        previous_artifact=thumbnail,
                    ),
                )
                layout.addWidget(regenerate_button, alignment=_LEFT)
        elif script_approved:
            layout.addWidget(small_muted("Not generated yet."))

            audience_input = QLineEdit("General audience")
            layout.addWidget(audience_input)

            generate_button = button(
                "Generate thumbnail", variant="primary", icon_name="image"
            )
            generate_button.clicked.connect(
                lambda: self._handle_generate_thumbnail(audience_input.text()),
            )
            layout.addWidget(generate_button, alignment=_LEFT)
        else:
            layout.addWidget(small_muted("Requires an approved script."))

        self._layout.addWidget(frame)

    @staticmethod
    def _build_script_lock_staleness_banner(
        layout: QVBoxLayout,
        *,
        job: VideoJob,
        source_script_lock_hash: str | None,
    ) -> None:
        """
        Step 2 (SEO, Thumbnail & Publishing Reconciliation), SEO-4:
        precise, dependency-aware staleness rather than a global flag -
        mirrors the same script_lock_hash-comparison pattern already
        used for ProductionSemanticBrief/VisualContinuityBible.

        Silent when the job has no lock yet (nothing to compare
        against) or the hashes genuinely match.
        """

        if job.script_lock is None:
            return

        current_hash = job.script_lock.script_content_hash

        if source_script_lock_hash is None:
            layout.addWidget(
                status_label(
                    "Built before the script was locked - "
                    "regenerate to bind it to the current script.",
                    role="warning",
                )
            )

            return

        if source_script_lock_hash != current_hash:
            layout.addWidget(
                status_label(
                    "Stale: the script has changed since this was "
                    "built. Regenerate to match the current script.",
                    role="warning",
                )
            )

    def _build_final_export_card(self, job: VideoJob) -> None:
        frame, layout = card("Final export", icon_name="export")

        assert self._job_id is not None

        final_export = self._job_store.get_final_export(self._job_id)
        render_result = self._job_store.get_render_result(self._job_id)
        seo_package = self._job_store.get_seo_package(self._job_id)
        thumbnail = self._job_store.get_thumbnail(self._job_id)

        if final_export is not None:
            status_role = (
                "success" if final_export.status.value == "approved" else "warning"
            )

            layout.addWidget(
                status_label(f"Status: {final_export.status.value}", role=status_role)
            )
            layout.addWidget(small_muted(f"Video: {final_export.final_video_path}"))
            layout.addWidget(
                small_muted(f"Export directory: {final_export.export_directory}")
            )

            self._build_qc_summary(layout, final_export)

            actions_row_widgets: list[QWidget] = []

            open_folder_button = button(
                "Open output folder",
                icon_name="folder",
            )
            open_folder_button.clicked.connect(
                lambda: self._handle_open_output_folder(final_export),
            )
            actions_row_widgets.append(open_folder_button)

            if final_export.manifest_path is not None:
                copy_manifest_button = button(
                    "Copy manifest path",
                )
                copy_manifest_button.clicked.connect(
                    lambda: self._handle_copy_manifest_path(final_export),
                )
                actions_row_widgets.append(copy_manifest_button)

            for action_widget in actions_row_widgets:
                layout.addWidget(action_widget, alignment=_LEFT)
        elif render_result is not None and render_result.success:
            if seo_package is not None and thumbnail is not None:
                layout.addWidget(small_muted("Not built yet."))

                export_button = button(
                    "Build final export package",
                    variant="primary",
                    icon_name="export",
                )
                export_button.clicked.connect(self._handle_build_final_export)
                layout.addWidget(export_button, alignment=_LEFT)
            else:
                layout.addWidget(
                    small_muted("Requires an SEO package and a thumbnail."),
                )
        else:
            layout.addWidget(
                small_muted("Requires a successful render (see Render Workspace).")
            )

        self._layout.addWidget(frame)

    def _build_qc_summary(
        self,
        layout: QVBoxLayout,
        final_export: FinalExportPackage,
    ) -> None:
        """
        Show the Final Package screen's QC summary.

        Re-runs the same, cheap, deterministic (no LLM/network calls)
        validation the build step already ran, so the summary always
        reflects the package's current on-disk state rather than a
        stale snapshot from whenever it was last built.
        """

        validation = self._final_export_service.validation_service.validate(
            final_export
        )

        if validation.is_valid and not validation.has_warnings:
            layout.addWidget(status_label("QC: all checks passed.", role="success"))
            return

        for issue in validation.errors:
            layout.addWidget(status_label(f"QC error: {issue.message}", role="error"))

        for issue in validation.warnings:
            layout.addWidget(
                status_label(f"QC warning: {issue.message}", role="warning")
            )

    def _handle_open_output_folder(
        self,
        final_export: FinalExportPackage,
    ) -> None:
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(final_export.export_directory),
        )

    def _handle_copy_manifest_path(
        self,
        final_export: FinalExportPackage,
    ) -> None:
        if final_export.manifest_path is None:
            return

        clipboard = QApplication.clipboard()

        if clipboard is not None:
            clipboard.setText(final_export.manifest_path)

    def _handle_generate_seo(
        self,
        target_audience: str,
        *,
        previous_package: SEOPackage | None = None,
    ) -> None:
        job = self._current_job()

        if job is None:
            return

        try:
            result = self._seo_package_service.build(
                job,
                genre_id=job.genre_id,
                target_audience=target_audience,
                previous_package=previous_package,
            )
        except (RuntimeError, ValueError) as error:
            self._record_error(
                job,
                f"SEO generation failed: {error}",
                on_retry=lambda: self._handle_generate_seo(
                    target_audience,
                    previous_package=previous_package,
                ),
            )

            return

        assert self._job_id is not None
        self._job_store.set_seo_package(self._job_id, result.package)
        self._on_change()

    def _handle_generate_thumbnail(
        self,
        target_audience: str,
        *,
        previous_artifact: ThumbnailArtifact | None = None,
    ) -> None:
        job = self._current_job()

        if job is None:
            return

        try:
            context = SEOContextBuilder().build(
                job,
                genre_id=job.genre_id,
                target_audience=target_audience,
            )

            result = self._thumbnail_package_service.build(
                context,
                project_id=job.project_name,
                previous_artifact=previous_artifact,
            )
        except (RuntimeError, ValueError) as error:
            self._record_error(
                job,
                f"Thumbnail generation failed: {error}",
                on_retry=lambda: self._handle_generate_thumbnail(
                    target_audience,
                    previous_artifact=previous_artifact,
                ),
            )

            return

        assert self._job_id is not None
        self._job_store.set_thumbnail(self._job_id, result.artifact)
        self._on_change()

    def _handle_build_final_export(self) -> None:
        job = self._current_job()

        if job is None:
            return

        assert self._job_id is not None

        render_result = self._job_store.get_render_result(self._job_id)
        seo_package = self._job_store.get_seo_package(self._job_id)
        thumbnail = self._job_store.get_thumbnail(self._job_id)

        if render_result is None or seo_package is None or thumbnail is None:
            return

        try:
            result = self._final_export_service.build(
                render_result,
                project_id=job.project_name,
                resolution="1920x1080",
                frame_rate=30,
                seo_package=seo_package,
                thumbnail_artifact=thumbnail,
            )
        except (RuntimeError, ValueError) as error:
            self._record_error(
                job,
                f"Final export failed: {error}",
                on_retry=self._handle_build_final_export,
            )

            return

        self._job_store.set_final_export(self._job_id, result.package)
        self._on_change()

    def _current_job(self) -> VideoJob | None:
        if self._job_id is None:
            return None

        return self._job_store.get(self._job_id)

    def _record_error(
        self,
        job: VideoJob,
        message: str,
        *,
        on_retry: Callable[[], None] | None = None,
    ) -> None:
        job.errors.append(message)
        show_recoverable_error(self, "Step failed", message, on_retry=on_retry)
        self._on_change()
