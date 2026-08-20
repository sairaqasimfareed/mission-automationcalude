from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from src.desktop.job_store import JobStore
from src.desktop.views.clip_workspace_view import ClipWorkspaceView
from src.desktop.views.content_studio_view import ContentStudioView
from src.desktop.views.editing_timeline_view import EditingTimelineView
from src.desktop.views.packaging_view import PackagingView
from src.desktop.views.production_audio_view import ProductionAudioView
from src.desktop.views.quality_center_view import QualityCenterView
from src.desktop.views.render_workspace_view import RenderWorkspaceView
from src.desktop.widgets import button, heading, muted, small_muted, status_label
from src.models.video_job import VideoJob
from src.services.content_intelligence_pipeline import ContentIntelligencePipeline
from src.services.content_pipeline import ContentPipeline
from src.services.final_export.final_export_service import FinalExportService
from src.services.media_generation_pipeline import MediaGenerationPipeline
from src.services.project_header_service import ProjectHeaderService
from src.services.project_render_runtime_factory import ProjectRenderRuntimeFactory
from src.services.scene_asset_workflow_service import SceneAssetWorkflowService
from src.services.seo.seo_package_service import SEOPackageService
from src.services.thumbnail.thumbnail_package_service import ThumbnailPackageService

_READINESS_HEADER_ROLE = {
    "blocked": "error",
    "ready for render": "warning",
    "ready for final export": "warning",
    "completed": "success",
}

_LEFT = Qt.AlignmentFlag.AlignLeft


class ProjectWorkspaceView(QWidget):
    """
    Project workspace shell.

    Splits what used to be one long scrolling card list (every pipeline
    stage stacked in a single view) into seven focused workspaces -
    Content Studio, Clip Workspace, Production Audio, Editing Timeline,
    Render Workspace, Quality Center, Packaging - switched by the nav
    row below the project heading. Each workspace owns its own cards
    and handlers; this shell only owns navigation and keeps them all in
    sync.

    Content Studio, Render Workspace, and Packaging cover pipeline
    steps that already had individually-triggered UI actions before
    this split. Quality Center adds a genuinely new trigger for
    PolicyService, which existed in the backend but was wired up
    nowhere. Clip Workspace, Production Audio, and Editing Timeline
    are review panels over real VideoJob/audio_timeline/video_timeline
    data rather than standalone triggers - voice generation and
    timeline building currently run as internal steps of one atomic
    render call (RenderOrchestratorService's registered pipeline
    stages), with no backend support yet for pausing after just one of
    them.
    """

    def __init__(
        self,
        *,
        job_store: JobStore,
        content_pipeline: ContentPipeline,
        content_intelligence_pipeline: ContentIntelligencePipeline,
        render_runtime_factory: ProjectRenderRuntimeFactory,
        asset_workflow_service: SceneAssetWorkflowService,
        media_generation_pipeline: MediaGenerationPipeline,
        final_export_service: FinalExportService,
        seo_package_service: SEOPackageService,
        thumbnail_package_service: ThumbnailPackageService,
        on_back: Callable[[], None],
    ) -> None:
        super().__init__()

        self._job_store = job_store
        self._on_back = on_back
        self._job_id: UUID | None = None
        self._project_header_service = ProjectHeaderService()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(12)

        back_button = button("Back to dashboard", variant="ghost", icon_name="back")
        back_button.clicked.connect(lambda: self._on_back())
        outer.addWidget(back_button, alignment=_LEFT)

        self._heading = heading("")
        outer.addWidget(self._heading)

        # Persistent, cross-tab summary of the nine canonical-state
        # fields (ProjectHeaderService) - rebuilt on every refresh()
        # alongside every workspace tab, so it never drifts out of
        # sync with what the tabs themselves show.
        self._header_row_container = QWidget()
        self._header_row_layout = QHBoxLayout(self._header_row_container)
        self._header_row_layout.setContentsMargins(0, 0, 0, 0)
        self._header_row_layout.setSpacing(16)
        outer.addWidget(self._header_row_container)

        self._missing_label = muted("Project not found.")
        self._missing_label.setVisible(False)
        outer.addWidget(self._missing_label)

        self.content_studio = ContentStudioView(
            job_store=job_store,
            content_pipeline=content_pipeline,
            content_intelligence_pipeline=content_intelligence_pipeline,
            on_change=self.refresh,
        )
        self.render_workspace = RenderWorkspaceView(
            job_store=job_store,
            render_runtime_factory=render_runtime_factory,
            asset_workflow_service=asset_workflow_service,
            on_change=self.refresh,
        )
        self.clip_workspace = ClipWorkspaceView(
            job_store=job_store,
            asset_workflow_service=asset_workflow_service,
            on_change=self.refresh,
        )
        self.production_audio = ProductionAudioView(
            job_store=job_store,
            media_generation_pipeline=media_generation_pipeline,
            on_change=self.refresh,
        )
        self.editing_timeline = EditingTimelineView(
            job_store=job_store,
            on_change=self.refresh,
        )
        self.quality_center = QualityCenterView(
            job_store=job_store,
            on_change=self.refresh,
        )
        self.packaging = PackagingView(
            job_store=job_store,
            seo_package_service=seo_package_service,
            thumbnail_package_service=thumbnail_package_service,
            final_export_service=final_export_service,
            on_change=self.refresh,
        )

        self._workspaces: list[tuple[str, str, QWidget]] = [
            ("Content", "research", self.content_studio),
            ("Clips", "clapper", self.clip_workspace),
            ("Audio", "audio", self.production_audio),
            ("Timeline", "timeline", self.editing_timeline),
            ("Render", "play", self.render_workspace),
            ("Quality", "shield", self.quality_center),
            ("Packaging", "package", self.packaging),
        ]

        self._stack = QStackedWidget()

        nav_row = QHBoxLayout()
        nav_row.setSpacing(8)

        self._nav_buttons: list[tuple[QWidget, QWidget]] = []

        for label, icon_name, workspace in self._workspaces:
            nav_button = button(label, icon_name=icon_name)
            nav_button.clicked.connect(
                lambda checked=False, target=workspace: self._show_workspace(target)
            )
            nav_row.addWidget(nav_button)
            self._stack.addWidget(workspace)
            self._nav_buttons.append((nav_button, workspace))

        nav_row.addStretch()

        outer.addLayout(nav_row)
        outer.addWidget(self._stack, stretch=1)

        self._show_workspace(self.content_studio)

    def set_job(self, job_id: UUID) -> None:
        """Display one job, replacing any previously displayed job."""

        self._job_id = job_id

        for _, _, workspace in self._workspaces:
            workspace.set_job(job_id)  # type: ignore[attr-defined]

        self.refresh()

    def refresh(self) -> None:
        """Reload the current job once and push it to every workspace."""

        if self._job_id is None:
            return

        job = self._job_store.get(self._job_id)

        if job is None:
            self._heading.setText("")
            self._clear_header_row()
            self._missing_label.setVisible(True)
            self._stack.setVisible(False)

            return

        # VideoJob is mutated in place by workspace handlers (e.g.
        # `job.research = research`), then this refresh() is called -
        # see JsonJobStore's docstring for why add() here is what
        # actually persists that mutation.
        self._job_store.add(job)

        self._missing_label.setVisible(False)
        self._stack.setVisible(True)
        self._heading.setText(job.project_name)
        self._refresh_header_row(job)

    def _clear_header_row(self) -> None:
        while self._header_row_layout.count():
            item = self._header_row_layout.takeAt(0)

            if item is None:
                continue

            widget = item.widget()

            if widget is not None:
                widget.deleteLater()

    def _refresh_header_row(self, job: VideoJob) -> None:
        self._clear_header_row()

        summary = self._project_header_service.summarize(job)

        fields = [
            ("Mode", summary.production_mode),
            ("Stage", summary.current_stage),
            ("Approval", summary.approval_mode),
            ("Next approval", summary.next_approval),
            ("Quality", summary.quality_state),
            ("Budget", summary.budget_state),
            ("Automation", summary.automation_state),
        ]

        for label, value in fields:
            self._header_row_layout.addWidget(small_muted(f"{label}: {value}"))

        readiness_role = _READINESS_HEADER_ROLE.get(summary.readiness_state, "warning")
        self._header_row_layout.addWidget(
            status_label(f"Readiness: {summary.readiness_state}", role=readiness_role)
        )
        self._header_row_layout.addStretch()

        self._refresh_all(job)

    def _refresh_all(self, job: VideoJob) -> None:
        for _, _, workspace in self._workspaces:
            workspace.refresh(job)  # type: ignore[attr-defined]

    def _show_workspace(self, target: QWidget) -> None:
        self._stack.setCurrentWidget(target)

        for nav_button, workspace in self._nav_buttons:
            nav_button.setProperty(
                "variant", "primary" if workspace is target else None
            )
            nav_button.style().unpolish(nav_button)
            nav_button.style().polish(nav_button)
