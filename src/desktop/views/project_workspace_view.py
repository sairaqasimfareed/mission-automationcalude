from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from src.desktop.job_store import JobStore
from src.desktop.views.clip_workspace_view import ClipWorkspaceView
from src.desktop.views.compiled_prompt_view import CompiledPromptView
from src.desktop.views.content_studio_view import ContentStudioView
from src.desktop.views.editing_timeline_view import EditingTimelineView
from src.desktop.views.packaging_view import PackagingView
from src.desktop.views.production_audio_view import ProductionAudioView
from src.desktop.views.quality_center_view import QualityCenterView
from src.desktop.views.render_workspace_view import RenderWorkspaceView
from src.desktop.widgets import button, card, heading, muted, small_muted, status_label
from src.models.final_export import FinalExportPackage
from src.models.production_readiness import ReadinessState
from src.models.seo import SEOPackage
from src.models.thumbnail import ThumbnailArtifact
from src.models.video_job import VideoJob
from src.services.content_intelligence_pipeline import ContentIntelligencePipeline
from src.services.content_pipeline import ContentPipeline
from src.services.content_studio_journey_service import (
    JOURNEY_STATUS_LABEL,
    JOURNEY_STATUS_ROLE,
    JourneyCheckpointStatus,
)
from src.services.enriched_scene_prompt_service import EnrichedScenePromptService
from src.services.fact_check_service import FactCheckService
from src.services.final_export.final_export_service import FinalExportService
from src.services.google_flow_generation_ledger_service import (
    GoogleFlowGenerationLedgerService,
)
from src.services.media_generation_pipeline import MediaGenerationPipeline
from src.services.muse_generation_ledger_service import MuseGenerationLedgerService
from src.services.opening_title_card_service import OpeningTitleCardService
from src.services.production_readiness_service import ProductionReadinessService
from src.services.project_header_service import ProjectHeaderService
from src.services.project_production_journey_service import (
    ProjectProductionJourneyService,
)
from src.services.project_render_runtime_factory import ProjectRenderRuntimeFactory
from src.services.registry.provider_registry import ProviderRegistry
from src.services.reviewer_service import ReviewerService
from src.services.scene_asset_workflow_service import SceneAssetWorkflowService
from src.services.scene_generation_dispatch_service import (
    SceneGenerationDispatchService,
)
from src.services.scene_video_generation_service import SceneVideoGenerationService
from src.services.seo.seo_package_service import SEOPackageService
from src.services.thumbnail.thumbnail_package_service import ThumbnailPackageService
from src.services.topic_candidate_generation_service import (
    TopicCandidateGenerationService,
)

# Which workspace tab a ProductionReadinessService blocker's `.stage`
# corresponds to - lets "Run / Resume" jump straight to whatever the
# job's own readiness evaluation already says is next, instead of the
# GUI inventing a second, competing notion of "what's next." Content-
# blocker stages ("content_intelligence") and approval-blocker stages
# (the individual ContentIntelligencePipeline sub-stage names each
# gate() call passes - see _approval_blockers()) both land on Content
# Studio, since every one of those stages is a panel inside that tab.
_BLOCKER_STAGE_TAB = {
    "content_intelligence": "content_studio",
    "audience_promise": "content_studio",
    # Regression fix (found via external audit): Phase 7's research_plan
    # approval gate (ApprovalGateService.gate(..., stage="research_plan"))
    # produces a Blocker with this exact stage value - without an entry
    # here, Run/Resume silently did nothing while a project was blocked
    # on "Approve Brief & Start Research."
    "research_plan": "content_studio",
    "research": "content_studio",
    "story_angles": "content_studio",
    "narrative_architecture": "content_studio",
    "hooks": "content_studio",
    "script": "content_studio",
    "asset_acquisition": "clip_workspace",
    "production_audio": "production_audio",
    "editing": "editing_timeline",
    "render": "render_workspace",
    "policy": "quality_center",
    "final_preview": "quality_center",
}

# Fallback when there are no blockers at all (report.blockers is
# empty) - the readiness state itself still says what's next.
_READINESS_STATE_TAB = {
    ReadinessState.READY_FOR_RENDER: "render_workspace",
    ReadinessState.READY_FOR_FINAL_EXPORT: "packaging",
    ReadinessState.COMPLETED: "packaging",
}

_READINESS_HEADER_ROLE = {
    "blocked": "error",
    "ready for render": "warning",
    "ready for final export": "warning",
    "completed": "success",
}

# How many status-card checkpoints share one row before wrapping to
# the next - purely a layout choice (no flow-layout widget exists in
# this app today), tuned so the full 16-checkpoint journey (8 content
# + Scene Planning/Assets/Voice & Audio/Timeline/Render/SEO/Thumbnail/
# Final Export) reads as a few short rows rather than one very long
# horizontal strip or a single cramped one.
_STATUS_CARD_ITEMS_PER_ROW = 5

_LEFT = Qt.AlignmentFlag.AlignLeft


class ProjectWorkspaceView(QWidget):
    """
    Project workspace shell.

    Splits what used to be one long scrolling card list (every pipeline
    stage stacked in a single view) into seven focused workspaces -
    Content Studio, Clip Workspace, Production Audio, Editing Timeline,
    Render Workspace, Quality Center, Packaging - switched by a left
    sidebar that stays visible beside the working panel, the way an
    IDE's or a video editor's shell does, rather than a top row that
    scrolls away. A persistent header above both (ProjectHeaderService)
    keeps the project's canonical state visible no matter which
    workspace is showing, with a "Run / Resume" action that jumps
    straight to whatever ProductionReadinessService says is next. Each
    workspace owns its own cards and handlers; this shell only owns
    navigation and keeps them all in sync.

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
        reviewer_service: ReviewerService,
        topic_candidate_generation_service: TopicCandidateGenerationService,
        fact_check_service: FactCheckService,
        on_back: Callable[[], None],
        scene_video_generation_service: SceneVideoGenerationService | None = None,
        scene_generation_dispatch_service: SceneGenerationDispatchService | None = None,
        provider_registry: ProviderRegistry | None = None,
        opening_title_card_service: OpeningTitleCardService | None = None,
    ) -> None:
        super().__init__()

        self._job_store = job_store
        self._on_back = on_back
        self._job_id: UUID | None = None
        self._project_header_service = ProjectHeaderService()
        self._readiness_service = ProductionReadinessService()
        self._journey_service = ProjectProductionJourneyService()
        # Real-world finding, 2026-09-30: expanded by default, the
        # full 16-checkpoint status card ate enough vertical space to
        # crowd out the actual workspace tab beneath it (confirmed
        # live). Collapsed by default instead - a pure GUI display
        # preference, not a fact about the video (AGENTS.md rule 4),
        # so it's fine to keep as plain view state rather than
        # persisting it on VideoJob.
        self._status_card_expanded = False

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
        # sync with what the tabs themselves show. The trailing
        # Run / Resume button is rebuilt along with it (cheap, and
        # keeps this row's construction in one place) rather than kept
        # as a separate persistent widget.
        self._header_row_container = QWidget()
        self._header_row_layout = QHBoxLayout(self._header_row_container)
        self._header_row_layout.setContentsMargins(0, 0, 0, 0)
        self._header_row_layout.setSpacing(16)
        outer.addWidget(self._header_row_container)

        # Persistent, cross-tab "everything and its status" card
        # (ProjectProductionJourneyService) - the user's own explicit
        # ask, 2026-09-30, after the header's "Stage" field turned out
        # to be misleading for a real project: one place that lists
        # every real production step (content through packaging) with
        # its own status, visible on every tab rather than only inside
        # Content Studio. Rebuilt fresh alongside the header row on
        # every refresh() - same "never trust a stale verdict"
        # convention the journey service itself follows.
        self._status_card_container = QWidget()
        self._status_card_container_layout = QVBoxLayout(self._status_card_container)
        self._status_card_container_layout.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._status_card_container)

        self._missing_label = muted("Project not found.")
        self._missing_label.setVisible(False)
        outer.addWidget(self._missing_label)

        self.content_studio = ContentStudioView(
            job_store=job_store,
            content_pipeline=content_pipeline,
            content_intelligence_pipeline=content_intelligence_pipeline,
            reviewer_service=reviewer_service,
            topic_candidate_generation_service=topic_candidate_generation_service,
            fact_check_service=fact_check_service,
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
            scene_video_generation_service=scene_generation_dispatch_service,
            provider_registry=provider_registry,
        )
        self.compiled_prompts = CompiledPromptView(
            job_store=job_store,
            on_change=self.refresh,
            enriched_scene_prompt_service=EnrichedScenePromptService(
                scene_video_generation_service=scene_video_generation_service,
            ),
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
            approval_gate_service=content_intelligence_pipeline.approval_gate_service,
            opening_title_card_service=opening_title_card_service,
        )

        self._workspaces: list[tuple[str, str, str, QWidget]] = [
            ("Content", "research", "content_studio", self.content_studio),
            # Real-world finding, 2026-09-30: a scene's real, measured
            # narration duration - set only by real voice generation,
            # never by the pre-generation estimate - is what both
            # correct clip duration sizing and multi-clip scene
            # splitting (SceneClipSplitPlanningService) actually need.
            # Audio now comes before Clips so the natural left-to-right
            # workflow order matches this real data dependency, rather
            # than inviting an operator to generate clips first and
            # silently fall back to the estimate the whole time.
            ("Audio", "audio", "production_audio", self.production_audio),
            ("Clips", "clapper", "clip_workspace", self.clip_workspace),
            ("Prompts", "tag", "compiled_prompts", self.compiled_prompts),
            ("Timeline", "timeline", "editing_timeline", self.editing_timeline),
            ("Render", "play", "render_workspace", self.render_workspace),
            ("Quality", "shield", "quality_center", self.quality_center),
            ("Packaging", "package", "packaging", self.packaging),
        ]
        self._workspace_by_tab_name: dict[str, QWidget] = {
            tab_name: workspace for _, _, tab_name, workspace in self._workspaces
        }

        self._stack = QStackedWidget()

        # A left sidebar rather than a top button row - the shell stays
        # around the user the way an IDE's or a video editor's does,
        # with the working panel changing beside a nav that's always
        # visible, not a strip that scrolls out of view.
        sidebar_container = QWidget()
        sidebar = QVBoxLayout(sidebar_container)
        sidebar.setContentsMargins(0, 0, 0, 0)
        sidebar.setSpacing(6)
        sidebar_container.setFixedWidth(180)

        self._nav_buttons: list[tuple[QWidget, QWidget]] = []

        for label, icon_name, _tab_name, workspace in self._workspaces:
            nav_button = button(label, icon_name=icon_name)
            nav_button.clicked.connect(
                lambda checked=False, target=workspace: self._show_workspace(target)
            )
            sidebar.addWidget(nav_button)
            self._stack.addWidget(workspace)
            self._nav_buttons.append((nav_button, workspace))

        sidebar.addStretch()

        body = QHBoxLayout()
        body.setSpacing(20)
        body.addWidget(sidebar_container)
        body.addWidget(self._stack, stretch=1)

        outer.addLayout(body, stretch=1)

        self._show_workspace(self.content_studio)

    def set_job(self, job_id: UUID) -> None:
        """Display one job, replacing any previously displayed job."""

        self._job_id = job_id
        self._reconcile_generation_attempts_on_open(job_id)

        for _, _, _, workspace in self._workspaces:
            workspace.set_job(job_id)  # type: ignore[attr-defined]

        self.refresh()

    def _reconcile_generation_attempts_on_open(self, job_id: UUID) -> None:
        """
        MRA-PRE-2 (Pre-Installer Master Audit, persistence/restart
        audit) real finding: `GoogleFlowGenerationLedgerService.
        reconcile_on_restart()` has existed and been tested since GF-1
        - any Google Flow generation attempt still recorded as
        SUBMITTING when the application closed or crashed mid-
        submission is meant to be reconciled to SUBMISSION_UNCERTAIN,
        the credit-sensitive-state rule's own honest "we don't know"
        state - but nothing in the real application ever called it.
        A project reopened after an interruption would show that
        attempt stuck at SUBMITTING forever, an inaccurate state that
        would never self-correct on its own.

        Real-world finding, 2026-09-30: `MuseGenerationLedgerService.
        reconcile_on_restart()` (the exact same method, built to the
        exact same contract, for Muse's own ledger) had the identical
        gap - built, tested, and never called from here either, since
        this method only ever reconciled Flow's own ledger even after
        Muse existed as a second provider. Both now run on every
        project open.

        Runs once per project open, not on every refresh() (this view
        refreshes far more often than once per action) - reconciling
        is only ever meaningful right after a restart, and
        reconcile_on_restart() is a no-op once nothing is left at
        SUBMITTING, so repeating it here would just be wasted work,
        not a correctness requirement.
        """

        job = self._job_store.get(job_id)

        if job is None:
            return

        flow_reconciled = GoogleFlowGenerationLedgerService.reconcile_on_restart(job)
        muse_reconciled = MuseGenerationLedgerService.reconcile_on_restart(job)

        if flow_reconciled or muse_reconciled:
            self._job_store.add(job)

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

        # SEO package / thumbnail / final export live in JobStore, not
        # on VideoJob itself - fetched once here and reused for both
        # the header's Stage field and the full status card below, so
        # a project that has already packaged doesn't show either one
        # as "Not started".
        seo_package = self._job_store.get_seo_package(job.id)
        thumbnail = self._job_store.get_thumbnail(job.id)
        final_export = self._job_store.get_final_export(job.id)

        summary = self._project_header_service.summarize(
            job,
            seo_package=seo_package,
            thumbnail=thumbnail,
            final_export=final_export,
        )

        fields = [
            ("Mode", summary.production_mode),
            ("Genre", summary.genre),
            ("Duration", summary.target_duration),
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

        run_resume_button = button("Run / Resume", variant="primary", icon_name="play")
        run_resume_button.clicked.connect(self._handle_run_resume)
        self._header_row_layout.addWidget(run_resume_button)

        self._refresh_status_card(
            job,
            seo_package=seo_package,
            thumbnail=thumbnail,
            final_export=final_export,
        )

        self._refresh_all(job)

    def _refresh_status_card(
        self,
        job: VideoJob,
        *,
        seo_package: SEOPackage | None,
        thumbnail: ThumbnailArtifact | None,
        final_export: FinalExportPackage | None,
    ) -> None:
        while self._status_card_container_layout.count():
            item = self._status_card_container_layout.takeAt(0)

            if item is None:
                continue

            widget = item.widget()

            if widget is not None:
                widget.deleteLater()

        checkpoints = self._journey_service.compute(
            job,
            seo_package=seo_package,
            thumbnail=thumbnail,
            final_export=final_export,
        )

        approved_count = sum(
            1
            for checkpoint in checkpoints
            if checkpoint.status == JourneyCheckpointStatus.APPROVED
        )

        toggle_button = button(
            "Hide details" if self._status_card_expanded else "Show details"
        )
        toggle_button.clicked.connect(self._handle_toggle_status_card)

        frame, layout = card(
            f"Project status ({approved_count}/{len(checkpoints)} approved)",
            icon_name="dashboard",
            header_widget=toggle_button,
        )

        if self._status_card_expanded:
            for start in range(0, len(checkpoints), _STATUS_CARD_ITEMS_PER_ROW):
                row_layout = QHBoxLayout()
                row_layout.setSpacing(10)

                for checkpoint in checkpoints[
                    start : start + _STATUS_CARD_ITEMS_PER_ROW
                ]:
                    role = JOURNEY_STATUS_ROLE[checkpoint.status]
                    text = (
                        f"{checkpoint.label}: "
                        f"{JOURNEY_STATUS_LABEL[checkpoint.status]}"
                    )

                    if role is None:
                        row_layout.addWidget(small_muted(text))
                    else:
                        row_layout.addWidget(status_label(text, role=role))

                row_layout.addStretch()
                layout.addLayout(row_layout)

        self._status_card_container_layout.addWidget(frame)

    def _handle_toggle_status_card(self) -> None:
        self._status_card_expanded = not self._status_card_expanded
        self.refresh()

    def _refresh_all(self, job: VideoJob) -> None:
        """
        Real-world finding, 2026-09-26: this loop rebuilds every
        workspace tab in one synchronous burst - Content Studio's own
        scroll-position-preserving refresh() was built and tested
        against refreshing *itself* repeatedly, never against seven
        sibling workspaces' own teardown/rebuild work happening in the
        same burst, which turned out to disturb its restore cycle's
        timing enough to reintroduce the exact "snaps back to the top"
        bug that view's own refresh() otherwise fixes for its direct
        callers (e.g. its own stage-tab clicks). Content Studio's
        capture/restore is pulled out here and run once across the
        whole burst instead of once per tab, so nothing sibling tabs
        do while rebuilding can race it - see ContentStudioView.
        refresh()'s own docstring for the full history.
        """

        content_studio_scroll_value = self.content_studio.capture_scroll_position(
            job.id
        )

        for _, _, tab_name, workspace in self._workspaces:
            if tab_name == "content_studio":
                workspace.refresh(job, manage_scroll=False)  # type: ignore[attr-defined]
            else:
                workspace.refresh(job)  # type: ignore[attr-defined]

        self.content_studio.restore_scroll_position(content_studio_scroll_value)

    def _current_job(self) -> VideoJob | None:
        if self._job_id is None:
            return None

        return self._job_store.get(self._job_id)

    def _handle_run_resume(self) -> None:
        """
        Jump to whatever ProductionReadinessService already says is
        next for this project - the same signal Quality Center's
        readiness card reads, so this button never invents a second,
        competing notion of "what's next." Deliberately navigational
        rather than auto-executing: each destination workspace still
        owns deciding exactly what action to run there (e.g. Render
        Workspace's own asset-decision flow), matching this shell's
        role as orchestration/navigation over existing capabilities,
        not a new automation layer.
        """

        job = self._current_job()

        if job is None:
            return

        report = self._readiness_service.evaluate(job)

        tab_name: str | None = None

        if report.blockers:
            tab_name = _BLOCKER_STAGE_TAB.get(report.blockers[0].stage)

        if tab_name is None:
            tab_name = _READINESS_STATE_TAB.get(report.state)

        if tab_name is None:
            return

        target = self._workspace_by_tab_name.get(tab_name)

        if target is not None:
            self._show_workspace(target)

    def _show_workspace(self, target: QWidget) -> None:
        self._stack.setCurrentWidget(target)

        for nav_button, workspace in self._nav_buttons:
            nav_button.setProperty(
                "variant", "primary" if workspace is target else None
            )
            nav_button.style().unpolish(nav_button)
            nav_button.style().polish(nav_button)
