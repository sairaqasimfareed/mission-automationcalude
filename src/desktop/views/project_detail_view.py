from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.desktop.job_store import InMemoryJobStore
from src.desktop.widgets import (
    badge,
    button,
    card,
    heading,
    muted,
    small_muted,
    status_label,
    subheading,
)
from src.models.asset_state import SceneAssetState
from src.models.enums import WorkflowStage
from src.models.scene import Scene
from src.models.video_job import VideoJob
from src.services.content_pipeline import ContentPipeline
from src.services.final_export.final_export_service import FinalExportService
from src.services.genre_profile_registry_service import (
    GenreProfileRegistryService,
)
from src.services.project_render_runtime_factory import (
    ProjectRenderRuntimeFactory,
)
from src.services.scene_asset_workflow_service import (
    SceneAssetWorkflowService,
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

_LEFT = Qt.AlignmentFlag.AlignLeft


class ProjectDetailView(QWidget):
    """
    Project detail view.

    Content generation (research, script, originality review, scene
    planning) runs as four separate, explicitly triggered steps rather
    than one atomic call, so current stage and progress stay genuinely
    observable (Sprint 26) instead of hidden inside ContentPipeline.run().
    Each step delegates to the same ContentPipeline sub-components
    ContentPipeline.run() itself sequences, so no business logic is
    duplicated here - only the UI-facing sequencing.

    Render runs in dry-run mode. When a scene has no local asset match,
    the asset stage pauses (WAITING_FOR_USER) rather than failing
    outright, and the Render card lets the user resolve each scene
    either by choosing a local file to upload, or by searching stock
    footage and selecting a result. Stock search runs immediately
    in-process (SceneAssetWorkflowService.search_stock(), mutating the
    same SceneAssetState objects already stored on the VideoJob from
    the paused render) - it does not need a render round trip.
    Submitting the final per-scene decisions re-runs render on the
    same VideoJob with them attached as user_input; selecting a stock
    candidate acquires it (downloads and stores it locally) within
    that same call. Checkpoint persistence
    (services.get_production_runtime()'s checkpoint_storage_root) lets
    that retry resume from the asset stage instead of re-running
    already-completed stages like voice generation against a job that
    already has voice tracks. Final export only becomes available once
    a render actually succeeds.
    """

    def __init__(
        self,
        *,
        job_store: InMemoryJobStore,
        content_pipeline: ContentPipeline,
        render_runtime_factory: ProjectRenderRuntimeFactory,
        asset_workflow_service: SceneAssetWorkflowService,
        final_export_service: FinalExportService,
        seo_package_service: SEOPackageService,
        thumbnail_package_service: ThumbnailPackageService,
        on_back: Callable[[], None],
    ) -> None:
        super().__init__()

        self._job_store = job_store
        self._content_pipeline = content_pipeline
        self._render_runtime_factory = render_runtime_factory
        self._asset_workflow_service = asset_workflow_service
        self._final_export_service = final_export_service
        self._seo_package_service = seo_package_service
        self._thumbnail_package_service = thumbnail_package_service
        self._on_back = on_back
        self._job_id: UUID | None = None
        self._manual_upload_paths: dict[int, str] = {}
        self._selected_stock_candidate_index: dict[int, int] = {}

        self._outer_layout = QVBoxLayout(self)
        self._outer_layout.setContentsMargins(24, 20, 24, 20)
        self._outer_layout.setSpacing(16)

        back_button = button("Back to dashboard", variant="ghost", icon_name="back")
        back_button.clicked.connect(lambda: self._on_back())
        self._outer_layout.addWidget(back_button, alignment=_LEFT)

        # A project can grow to 9+ cards (project, workflow, research,
        # script, originality, scenes, SEO, thumbnail, render - each
        # with per-scene sub-cards, plus final export). Without a
        # scroll area, that content is squeezed to fit the window
        # instead of extending below it, which visibly corrupts every
        # card's layout once the total height exceeds the window -
        # found by actually rendering this view, not by inspection.
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        content_container = QWidget()
        self._content_layout = QVBoxLayout(content_container)
        self._content_layout.setSpacing(16)
        self._content_layout.setContentsMargins(0, 0, 4, 0)

        scroll_area.setWidget(content_container)
        self._outer_layout.addWidget(scroll_area)

    def set_job(self, job_id: UUID) -> None:
        """Display one job, replacing any previously displayed job."""

        self._job_id = job_id
        self._manual_upload_paths = {}
        self._selected_stock_candidate_index = {}
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
            self._content_layout.addWidget(muted("Project not found."))

            return

        self._content_layout.addWidget(heading(job.project_name))

        self._build_project_card(job)
        self._build_workflow_card(job)
        self._build_research_card(job)
        self._build_script_card(job)
        self._build_originality_card(job)
        self._build_scenes_card(job)
        self._build_seo_card(job)
        self._build_thumbnail_card(job)
        self._build_render_card(job)
        self._build_final_export_card(job)

    def _build_project_card(self, job: VideoJob) -> None:
        frame, layout = card("Project", icon_name="folder")

        layout.addWidget(muted(f"Topic: {job.topic}"))
        layout.addWidget(muted(f"Niche: {job.niche}"))
        layout.addWidget(muted(f"Platform: {job.platform.value}"))

        self._content_layout.addWidget(frame)

    def _build_workflow_card(self, job: VideoJob) -> None:
        frame, layout = card("Workflow", icon_name="dashboard")

        layout.addWidget(
            badge(f"{job.current_stage.value} · {job.status.value}"),
        )

        if job.errors:
            layout.addWidget(
                status_label(
                    "Errors:\n" + "\n".join(f"- {error}" for error in job.errors),
                    role="error",
                )
            )

        if job.warnings:
            layout.addWidget(
                status_label(
                    "Warnings:\n"
                    + "\n".join(f"- {warning}" for warning in job.warnings),
                    role="warning",
                )
            )

        if job.research is None:
            action = button("Run research", variant="primary", icon_name="research")
            action.clicked.connect(self._handle_run_research)
            layout.addWidget(action, alignment=_LEFT)
        elif job.script is None:
            action = button("Run script", variant="primary", icon_name="script")
            action.clicked.connect(self._handle_run_script)
            layout.addWidget(action, alignment=_LEFT)
        elif job.originality_review is None:
            action = button(
                "Run originality review", variant="primary", icon_name="shield"
            )
            action.clicked.connect(self._handle_run_originality)
            layout.addWidget(action, alignment=_LEFT)
        elif not job.scenes:
            action = button("Plan scenes", variant="primary", icon_name="clapper")
            action.clicked.connect(self._handle_plan_scenes)
            layout.addWidget(action, alignment=_LEFT)
        else:
            layout.addWidget(
                status_label("Content generation steps are complete.", role="success")
            )

        self._content_layout.addWidget(frame)

    def _build_research_card(self, job: VideoJob) -> None:
        frame, layout = card("Research", icon_name="research")

        research = job.research

        if research is not None:
            layout.addWidget(badge(research.status.value))
            layout.addWidget(muted(research.research_summary))

            if research.claude_review_notes:
                layout.addWidget(
                    small_muted(
                        "Review notes: " + "; ".join(research.claude_review_notes)
                    )
                )
        else:
            layout.addWidget(small_muted("No research yet."))

        self._content_layout.addWidget(frame)

    def _build_script_card(self, job: VideoJob) -> None:
        frame, layout = card("Script", icon_name="script")

        script = job.script

        if script is not None:
            layout.addWidget(
                badge(f"{script.status.value} · {script.word_count} words")
            )
            layout.addWidget(muted(script.content))

            if script.claude_review_notes:
                layout.addWidget(
                    small_muted(
                        "Review notes: " + "; ".join(script.claude_review_notes)
                    )
                )
        else:
            layout.addWidget(small_muted("No script yet."))

        self._content_layout.addWidget(frame)

    def _build_originality_card(self, job: VideoJob) -> None:
        frame, layout = card("Originality review", icon_name="shield")

        review = job.originality_review

        if review is not None:
            layout.addWidget(badge(review.status.value))
            layout.addWidget(
                muted(
                    f"Originality: {review.originality_score} · "
                    f"Human value: {review.human_value_score} · "
                    f"Hook strength: {review.hook_strength_score}"
                )
            )

            if review.strengths:
                layout.addWidget(
                    small_muted("Strengths: " + ", ".join(review.strengths))
                )

            if review.weaknesses:
                layout.addWidget(
                    small_muted("Weaknesses: " + ", ".join(review.weaknesses))
                )

            if review.recommendations:
                layout.addWidget(
                    small_muted("Recommendations: " + ", ".join(review.recommendations))
                )
        else:
            layout.addWidget(small_muted("Not reviewed yet."))

        self._content_layout.addWidget(frame)

    def _build_scenes_card(self, job: VideoJob) -> None:
        frame, layout = card(f"Scenes ({len(job.scenes)})", icon_name="clapper")

        if job.scenes:
            for scene in job.scenes:
                row = QFrame()
                row.setProperty("sceneRow", True)
                row_layout = QVBoxLayout(row)
                row_layout.setContentsMargins(12, 8, 12, 8)
                row_layout.setSpacing(2)

                row_layout.addWidget(
                    subheading(
                        f"#{scene.scene_number} {scene.title} "
                        f"({scene.estimated_duration_seconds}s)"
                    )
                )
                row_layout.addWidget(small_muted(scene.narration))

                layout.addWidget(row)
        else:
            layout.addWidget(small_muted("No scenes planned yet."))

        self._content_layout.addWidget(frame)

    def _build_seo_card(self, job: VideoJob) -> None:
        frame, layout = card("SEO package", icon_name="tag")

        assert self._job_id is not None

        seo_package = self._job_store.get_seo_package(self._job_id)

        if seo_package is not None:
            layout.addWidget(
                subheading(seo_package.selected_title or ""),
            )
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

        self._content_layout.addWidget(frame)

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

        self._content_layout.addWidget(frame)

    def _build_render_card(self, job: VideoJob) -> None:
        frame, layout = card("Render", icon_name="play")

        assert self._job_id is not None

        waiting_scene_numbers = [
            state.scene_number
            for state in job.scene_asset_states
            if state.requires_user_decision
        ]

        render_result = self._job_store.get_render_result(self._job_id)

        if waiting_scene_numbers:
            layout.addWidget(
                muted(
                    "These scenes need a visual asset before render can "
                    "continue. For each one, either choose a local file to "
                    "upload, or search stock footage and select a result."
                )
            )

            for scene_number in waiting_scene_numbers:
                self._build_scene_asset_choice(
                    layout,
                    job=job,
                    scene_number=scene_number,
                )

            submit_button = button(
                "Submit choices and continue render",
                variant="primary",
                icon_name="play",
            )
            submit_button.clicked.connect(self._handle_submit_asset_decisions)
            layout.addWidget(submit_button, alignment=_LEFT)
        elif render_result is not None:
            layout.addWidget(
                status_label("Render succeeded.", role="success")
                if render_result.success
                else status_label("Render failed.", role="error")
            )
            layout.addWidget(badge(render_result.status.value))

            if render_result.render_result is not None:
                layout.addWidget(
                    small_muted(
                        f"Output file: {render_result.render_result.output_file}"
                    ),
                )

            if render_result.errors:
                layout.addWidget(
                    status_label(
                        "Errors:\n"
                        + "\n".join(f"- {error}" for error in render_result.errors),
                        role="error",
                    )
                )

            if render_result.warnings:
                layout.addWidget(
                    status_label(
                        "Warnings:\n"
                        + "\n".join(
                            f"- {warning}" for warning in render_result.warnings
                        ),
                        role="warning",
                    )
                )

            retry_button = button("Run render again", variant="ghost", icon_name="play")
            retry_button.clicked.connect(self._handle_run_render)
            layout.addWidget(retry_button, alignment=_LEFT)
        elif job.scenes:
            layout.addWidget(small_muted("Not rendered yet."))

            render_button = button("Run render", variant="primary", icon_name="play")
            render_button.clicked.connect(self._handle_run_render)
            layout.addWidget(render_button, alignment=_LEFT)
        else:
            layout.addWidget(small_muted("Requires planned scenes."))

        self._content_layout.addWidget(frame)

    def _build_scene_asset_choice(
        self,
        layout: QVBoxLayout,
        *,
        job: VideoJob,
        scene_number: int,
    ) -> None:
        frame = QFrame()
        frame.setProperty("sceneRow", True)

        inner_layout = QVBoxLayout(frame)
        inner_layout.setContentsMargins(12, 12, 12, 12)
        inner_layout.setSpacing(8)

        inner_layout.addWidget(subheading(f"Scene {scene_number}"))

        state = self._scene_asset_state(job, scene_number)
        stock_index = self._selected_stock_candidate_index.get(scene_number)
        manual_path = self._manual_upload_paths.get(scene_number)

        if (
            stock_index is not None
            and state is not None
            and 0 <= stock_index < len(state.stock_candidates)
        ):
            candidate = state.stock_candidates[stock_index]
            inner_layout.addWidget(
                status_label(
                    f"Selected stock result: {candidate.title} "
                    f"({candidate.provider})",
                    role="success",
                )
            )
        elif manual_path is not None:
            inner_layout.addWidget(
                status_label(f"Manual upload: {manual_path}", role="success")
            )
        else:
            inner_layout.addWidget(small_muted("No choice made yet."))

        choose_button = button("Choose file for manual upload", icon_name="upload")
        choose_button.clicked.connect(
            lambda checked=False, n=scene_number: (
                self._handle_choose_manual_upload(n)
            ),
        )
        inner_layout.addWidget(choose_button, alignment=_LEFT)

        query_input = QLineEdit()
        query_input.setPlaceholderText("Stock search query (optional)")

        if state is not None and state.stock_search_query:
            query_input.setPlaceholderText(state.stock_search_query)

        inner_layout.addWidget(query_input)

        search_button = button("Search stock footage", icon_name="search")
        search_button.clicked.connect(
            lambda checked=False, n=scene_number, q=query_input: (
                self._handle_search_stock(n, q.text())
            ),
        )
        inner_layout.addWidget(search_button, alignment=_LEFT)

        if state is not None and state.stock_candidates:
            for index, candidate in enumerate(state.stock_candidates):
                candidate_row = QFrame()
                candidate_layout = QVBoxLayout(candidate_row)
                candidate_layout.setContentsMargins(0, 4, 0, 4)
                candidate_layout.setSpacing(4)

                candidate_layout.addWidget(
                    small_muted(
                        f"{index + 1}. {candidate.title} - "
                        f"{candidate.provider or 'Unknown provider'} "
                        f"({candidate.license_type or 'unknown license'})"
                    )
                )

                select_button = button(
                    f"Select result {index + 1}",
                    variant="ghost",
                    icon_name="check",
                )
                select_button.clicked.connect(
                    lambda checked=False, n=scene_number, i=index: (
                        self._handle_select_stock_candidate(n, i)
                    ),
                )
                candidate_layout.addWidget(select_button, alignment=_LEFT)

                inner_layout.addWidget(candidate_row)

        layout.addWidget(frame)

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
            layout.addWidget(small_muted("Requires a successful render."))

        self._content_layout.addWidget(frame)

    def _handle_run_research(self) -> None:
        job = self._current_job()

        if job is None:
            return

        try:
            research = self._content_pipeline.research_pipeline.run(job.topic)
        except (RuntimeError, ValueError) as error:
            self._record_error(job, f"Research generation failed: {error}")

            return

        job.research = research
        job.current_stage = WorkflowStage.SCRIPT
        self.refresh()

    def _handle_run_script(self) -> None:
        job = self._current_job()

        if job is None or job.research is None:
            return

        try:
            script = self._content_pipeline.script_pipeline.run(job.research)
        except (RuntimeError, ValueError) as error:
            self._record_error(job, f"Script generation failed: {error}")

            return

        job.script = script
        job.current_stage = WorkflowStage.ORIGINALITY_REVIEW
        self.refresh()

    def _handle_run_originality(self) -> None:
        job = self._current_job()

        if job is None or job.script is None:
            return

        try:
            review = self._content_pipeline.originality_agent.analyze(job.script)
        except (RuntimeError, ValueError) as error:
            self._record_error(job, f"Originality review failed: {error}")

            return

        job.originality_review = review
        self.refresh()

    def _handle_plan_scenes(self) -> None:
        job = self._current_job()

        if job is None or job.script is None:
            return

        try:
            scenes = self._content_pipeline.scene_planner.plan(job.script)
        except (RuntimeError, ValueError) as error:
            self._record_error(job, f"Scene planning failed: {error}")

            return

        job.scenes = scenes
        job.current_stage = WorkflowStage.QUALITY_CHECK
        self.refresh()

    def _handle_generate_seo(self, target_audience: str) -> None:
        job = self._current_job()

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
            self._record_error(job, f"SEO generation failed: {error}")

            return

        assert self._job_id is not None
        self._job_store.set_seo_package(self._job_id, result.package)
        self.refresh()

    def _handle_generate_thumbnail(self, target_audience: str) -> None:
        job = self._current_job()

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
            self._record_error(job, f"Thumbnail generation failed: {error}")

            return

        assert self._job_id is not None
        self._job_store.set_thumbnail(self._job_id, result.artifact)
        self.refresh()

    def _handle_run_render(self) -> None:
        job = self._current_job()

        if job is None or not job.scenes:
            return

        self._execute_render(job)

    def _handle_choose_manual_upload(self, scene_number: int) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            f"Select video file for scene {scene_number}",
            "",
            "Video files (*.mp4 *.mov *.mkv *.webm *.avi *.m4v)",
        )

        if not file_path:
            return

        self._manual_upload_paths[scene_number] = file_path
        self._selected_stock_candidate_index.pop(scene_number, None)
        self.refresh()

    def _handle_search_stock(self, scene_number: int, query_text: str) -> None:
        job = self._current_job()

        if job is None:
            return

        scene = self._scene_by_number(job, scene_number)
        state = self._scene_asset_state(job, scene_number)

        if scene is None or state is None:
            return

        cleaned_query = query_text.strip()

        if cleaned_query:
            scene.stock_query = cleaned_query

        try:
            self._asset_workflow_service.search_stock(scene=scene, state=state)
        except (RuntimeError, ValueError) as error:
            self._record_error(job, f"Stock search failed: {error}")

            return

        self.refresh()

    def _handle_select_stock_candidate(
        self,
        scene_number: int,
        candidate_index: int,
    ) -> None:
        self._selected_stock_candidate_index[scene_number] = candidate_index
        self._manual_upload_paths.pop(scene_number, None)
        self.refresh()

    def _handle_submit_asset_decisions(self) -> None:
        job = self._current_job()

        if job is None:
            return

        waiting_scene_numbers = [
            state.scene_number
            for state in job.scene_asset_states
            if state.requires_user_decision
        ]

        missing_scene_numbers = [
            scene_number
            for scene_number in waiting_scene_numbers
            if scene_number not in self._manual_upload_paths
            and scene_number not in self._selected_stock_candidate_index
        ]

        if missing_scene_numbers:
            self._record_error(
                job,
                "Choose a file or select stock footage for every scene "
                "before submitting: "
                + ", ".join(str(number) for number in missing_scene_numbers),
            )

            return

        asset_decisions: list[dict[str, object]] = []

        for scene_number in waiting_scene_numbers:
            if scene_number in self._selected_stock_candidate_index:
                asset_decisions.append(
                    {
                        "scene_number": scene_number,
                        "decision": "use_stock",
                        "selected_candidate_index": (
                            self._selected_stock_candidate_index[scene_number]
                        ),
                        "project_id": job.project_name,
                    }
                )
            else:
                asset_decisions.append(
                    {
                        "scene_number": scene_number,
                        "decision": "manual_upload",
                        "manual_upload_path": (self._manual_upload_paths[scene_number]),
                        "project_id": job.project_name,
                    }
                )

        self._execute_render(job, user_input={"asset_decisions": asset_decisions})

    def _execute_render(
        self,
        job: VideoJob,
        *,
        user_input: dict[str, object] | None = None,
    ) -> None:
        genre_id = _DEFAULT_GENRE_IDS[0] if _DEFAULT_GENRE_IDS else "genre.default"

        try:
            render_orchestrator = self._render_runtime_factory.build(
                job=job,
                genre_id=genre_id,
            )
        except (RuntimeError, ValueError) as error:
            self._record_error(job, f"Render setup failed: {error}")

            return

        result = render_orchestrator.execute(
            job,
            dry_run=True,
            user_input=user_input,
        )

        assert self._job_id is not None
        self._job_store.set_render_result(self._job_id, result)
        self.refresh()

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
            self._record_error(job, f"Final export failed: {error}")

            return

        self._job_store.set_final_export(self._job_id, result.package)
        self.refresh()

    def _current_job(self) -> VideoJob | None:
        if self._job_id is None:
            return None

        return self._job_store.get(self._job_id)

    @staticmethod
    def _scene_by_number(job: VideoJob, scene_number: int) -> Scene | None:
        for scene in job.scenes:
            if scene.scene_number == scene_number:
                return scene

        return None

    @staticmethod
    def _scene_asset_state(
        job: VideoJob,
        scene_number: int,
    ) -> SceneAssetState | None:
        for state in job.scene_asset_states:
            if state.scene_number == scene_number:
                return state

        return None

    def _record_error(self, job: VideoJob, message: str) -> None:
        job.errors.append(message)
        QMessageBox.warning(self, "Step failed", message)
        self.refresh()
