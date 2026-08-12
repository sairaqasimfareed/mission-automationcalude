from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.desktop.job_store import InMemoryJobStore
from src.models.video_job import VideoJob
from src.services.genre_profile_registry_service import (
    GenreProfileRegistryService,
)
from src.services.seo.seo_context_builder import SEOContextBuilder
from src.services.seo.seo_package_service import SEOPackageService
from src.services.thumbnail.thumbnail_package_service import (
    ThumbnailPackageService,
)

_DEFAULT_GENRE_IDS = [
    profile.genre_id
    for profile in GenreProfileRegistryService.with_default_profiles().list_all()
]


def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setFrameShape(QFrame.Shape.StyledPanel)

    layout = QVBoxLayout(frame)
    layout.addWidget(QLabel(f"<h3>{title}</h3>"))

    return frame, layout


class ProjectDetailView(QWidget):
    """
    Project detail view.

    Note: render/final export are not reachable from this UI yet -
    ProjectRenderRuntimeFactory requires asset_workflow_service/
    genre_timeline_service, which have no automatic construction path
    (see MissionApplicationService and src/entrypoint.py). This view
    covers research, script, SEO package, and thumbnail generation
    only.
    """

    def __init__(
        self,
        *,
        job_store: InMemoryJobStore,
        seo_package_service: SEOPackageService,
        thumbnail_package_service: ThumbnailPackageService,
        on_back: Callable[[], None],
    ) -> None:
        super().__init__()

        self._job_store = job_store
        self._seo_package_service = seo_package_service
        self._thumbnail_package_service = thumbnail_package_service
        self._on_back = on_back
        self._job_id: UUID | None = None

        self._outer_layout = QVBoxLayout(self)

        back_button = QPushButton("< Back to dashboard")
        back_button.clicked.connect(lambda: self._on_back())
        self._outer_layout.addWidget(back_button)

        self._content_layout = QVBoxLayout()
        self._outer_layout.addLayout(self._content_layout)

    def set_job(self, job_id: UUID) -> None:
        """Display one job, replacing any previously displayed job."""

        self._job_id = job_id
        self.refresh()

    def refresh(self) -> None:
        """Rebuild the view from current job store state."""

        while self._content_layout.count():
            item = self._content_layout.takeAt(0)

            if item is None:
                continue

            widget = item.widget()

            if widget is not None:
                widget.deleteLater()

        if self._job_id is None:
            return

        job = self._job_store.get(self._job_id)

        if job is None:
            self._content_layout.addWidget(QLabel("Project not found."))

            return

        self._content_layout.addWidget(QLabel(f"<h2>{job.project_name}</h2>"))

        self._content_layout.addWidget(
            QLabel(f"Stage: {job.current_stage.value} | " f"Status: {job.status.value}")
        )

        note = QLabel(
            "Render and final export are not yet reachable from this "
            "app. This page covers research, script, SEO package, "
            "and thumbnail generation only."
        )
        note.setWordWrap(True)
        self._content_layout.addWidget(note)

        self._build_project_card(job)
        self._build_research_card(job)
        self._build_script_card(job)
        self._build_seo_card(job)
        self._build_thumbnail_card(job)

    def _build_project_card(self, job: VideoJob) -> None:
        frame, layout = _card("Project")

        layout.addWidget(QLabel(f"Topic: {job.topic}"))
        layout.addWidget(QLabel(f"Niche: {job.niche}"))
        layout.addWidget(QLabel(f"Platform: {job.platform.value}"))

        self._content_layout.addWidget(frame)

    def _build_research_card(self, job: VideoJob) -> None:
        frame, layout = _card("Research")

        research = job.research

        if research is not None:
            layout.addWidget(QLabel(f"Status: {research.status.value}"))

            summary = QLabel(research.research_summary)
            summary.setWordWrap(True)
            layout.addWidget(summary)
        else:
            layout.addWidget(QLabel("No research yet."))

        self._content_layout.addWidget(frame)

    def _build_script_card(self, job: VideoJob) -> None:
        frame, layout = _card("Script")

        script = job.script

        if script is not None:
            layout.addWidget(QLabel(f"Status: {script.status.value}"))
            layout.addWidget(QLabel(f"Word count: {script.word_count}"))

            content = QLabel(script.content)
            content.setWordWrap(True)
            layout.addWidget(content)
        else:
            layout.addWidget(QLabel("No script yet."))

        self._content_layout.addWidget(frame)

    def _build_seo_card(self, job: VideoJob) -> None:
        frame, layout = _card("SEO package")

        assert self._job_id is not None

        seo_package = self._job_store.get_seo_package(self._job_id)

        if seo_package is not None:
            layout.addWidget(
                QLabel(f"Selected title: {seo_package.selected_title}"),
            )

            description = QLabel(seo_package.description)
            description.setWordWrap(True)
            layout.addWidget(description)

            layout.addWidget(
                QLabel(f"Tags: {', '.join(seo_package.tags)}"),
            )
            layout.addWidget(
                QLabel(f"Hashtags: {' '.join(seo_package.hashtags)}"),
            )
        else:
            layout.addWidget(QLabel("Not generated yet."))

            audience_input = QLineEdit("General audience")
            layout.addWidget(audience_input)

            generate_button = QPushButton("Generate SEO package")
            generate_button.clicked.connect(
                lambda: self._handle_generate_seo(audience_input.text()),
            )
            layout.addWidget(generate_button)

        self._content_layout.addWidget(frame)

    def _build_thumbnail_card(self, job: VideoJob) -> None:
        frame, layout = _card("Thumbnail")

        assert self._job_id is not None

        thumbnail = self._job_store.get_thumbnail(self._job_id)

        if thumbnail is not None:
            layout.addWidget(
                QLabel(f"Hook text: {thumbnail.concept.hook_text}"),
            )
            layout.addWidget(
                QLabel(f"Source: {thumbnail.image_source_type.value}"),
            )
            layout.addWidget(QLabel(f"File: {thumbnail.file_path}"))
        else:
            layout.addWidget(QLabel("Not generated yet."))

            audience_input = QLineEdit("General audience")
            layout.addWidget(audience_input)

            generate_button = QPushButton("Generate thumbnail")
            generate_button.clicked.connect(
                lambda: self._handle_generate_thumbnail(audience_input.text()),
            )
            layout.addWidget(generate_button)

        self._content_layout.addWidget(frame)

    def _handle_generate_seo(self, target_audience: str) -> None:
        assert self._job_id is not None

        job = self._job_store.get(self._job_id)

        if job is None:
            return

        genre_id = _DEFAULT_GENRE_IDS[0] if _DEFAULT_GENRE_IDS else "genre.default"

        try:
            result = self._seo_package_service.build(
                job,
                genre_id=genre_id,
                target_audience=target_audience,
            )
        except (RuntimeError, ValueError) as error:
            QMessageBox.warning(self, "SEO generation failed", str(error))

            return

        self._job_store.set_seo_package(self._job_id, result.package)
        self.refresh()

    def _handle_generate_thumbnail(self, target_audience: str) -> None:
        assert self._job_id is not None

        job = self._job_store.get(self._job_id)

        if job is None:
            return

        genre_id = _DEFAULT_GENRE_IDS[0] if _DEFAULT_GENRE_IDS else "genre.default"

        try:
            context = SEOContextBuilder().build(
                job,
                genre_id=genre_id,
                target_audience=target_audience,
            )

            result = self._thumbnail_package_service.build(
                context,
                project_id=job.project_name,
            )
        except (RuntimeError, ValueError) as error:
            QMessageBox.warning(self, "Thumbnail generation failed", str(error))

            return

        self._job_store.set_thumbnail(self._job_id, result.artifact)
        self.refresh()
