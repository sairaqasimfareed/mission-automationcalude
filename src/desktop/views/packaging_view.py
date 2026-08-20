from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
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

        if seo_package is not None:
            layout.addWidget(subheading(seo_package.selected_title or ""))
            layout.addWidget(muted(seo_package.description))
            layout.addWidget(small_muted(f"Tags: {', '.join(seo_package.tags)}"))
            layout.addWidget(small_muted(f"Hashtags: {' '.join(seo_package.hashtags)}"))
        elif job.script is not None and job.script.status.value == "approved":
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

        if thumbnail is not None:
            layout.addWidget(subheading(thumbnail.concept.hook_text))
            layout.addWidget(
                small_muted(f"Source: {thumbnail.image_source_type.value}")
            )
            layout.addWidget(small_muted(f"File: {thumbnail.file_path}"))
        elif job.script is not None and job.script.status.value == "approved":
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

    def _build_final_export_card(self, job: VideoJob) -> None:
        frame, layout = card("Final export", icon_name="export")

        assert self._job_id is not None

        final_export = self._job_store.get_final_export(self._job_id)
        render_result = self._job_store.get_render_result(self._job_id)
        seo_package = self._job_store.get_seo_package(self._job_id)
        thumbnail = self._job_store.get_thumbnail(self._job_id)

        if final_export is not None:
            layout.addWidget(
                status_label(f"Status: {final_export.status.value}", role="success")
            )
            layout.addWidget(small_muted(f"Video: {final_export.final_video_path}"))
            layout.addWidget(
                small_muted(f"Export directory: {final_export.export_directory}")
            )
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

    def _handle_generate_seo(self, target_audience: str) -> None:
        job = self._current_job()

        if job is None:
            return

        try:
            result = self._seo_package_service.build(
                job,
                genre_id=job.genre_id,
                target_audience=target_audience,
            )
        except (RuntimeError, ValueError) as error:
            self._record_error(
                job,
                f"SEO generation failed: {error}",
                on_retry=lambda: self._handle_generate_seo(target_audience),
            )

            return

        assert self._job_id is not None
        self._job_store.set_seo_package(self._job_id, result.package)
        self._on_change()

    def _handle_generate_thumbnail(self, target_audience: str) -> None:
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
            )
        except (RuntimeError, ValueError) as error:
            self._record_error(
                job,
                f"Thumbnail generation failed: {error}",
                on_retry=lambda: self._handle_generate_thumbnail(target_audience),
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
