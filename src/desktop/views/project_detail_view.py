from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.desktop.job_store import InMemoryJobStore
from src.models.enums import WorkflowStage
from src.models.video_job import VideoJob
from src.services.content_pipeline import ContentPipeline
from src.services.final_export.final_export_service import FinalExportService
from src.services.genre_profile_registry_service import (
    GenreProfileRegistryService,
)
from src.services.project_render_runtime_factory import (
    ProjectRenderRuntimeFactory,
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

    Content generation (research, script, originality review, scene
    planning) runs as four separate, explicitly triggered steps rather
    than one atomic call, so current stage and progress stay genuinely
    observable (Sprint 26) instead of hidden inside ContentPipeline.run().
    Each step delegates to the same ContentPipeline sub-components
    ContentPipeline.run() itself sequences, so no business logic is
    duplicated here - only the UI-facing sequencing.

    Render runs in dry-run mode. When a scene has no local asset match,
    the asset stage pauses (WAITING_FOR_USER) rather than failing
    outright, and the Render card asks for a manual upload file per
    scene. Submitting those re-runs render on the same VideoJob with
    the decisions attached as user_input - checkpoint persistence
    (services.get_production_runtime()'s checkpoint_storage_root) lets
    the retry resume from the asset stage instead of re-running
    already-completed stages like voice generation against a job that
    already has voice tracks. No stock-footage acquisition path is
    wired in yet (it needs a VisualAssetRouter/StockFootageProvider
    chain with real HTTP downloads and no dry-run implementation
    exists), so manual upload is the only way a scene resolves today.
    Final export only becomes available once a render actually
    succeeds.
    """

    def __init__(
        self,
        *,
        job_store: InMemoryJobStore,
        content_pipeline: ContentPipeline,
        render_runtime_factory: ProjectRenderRuntimeFactory,
        final_export_service: FinalExportService,
        seo_package_service: SEOPackageService,
        thumbnail_package_service: ThumbnailPackageService,
        on_back: Callable[[], None],
    ) -> None:
        super().__init__()

        self._job_store = job_store
        self._content_pipeline = content_pipeline
        self._render_runtime_factory = render_runtime_factory
        self._final_export_service = final_export_service
        self._seo_package_service = seo_package_service
        self._thumbnail_package_service = thumbnail_package_service
        self._on_back = on_back
        self._job_id: UUID | None = None
        self._manual_upload_paths: dict[int, str] = {}

        self._outer_layout = QVBoxLayout(self)

        back_button = QPushButton("< Back to dashboard")
        back_button.clicked.connect(lambda: self._on_back())
        self._outer_layout.addWidget(back_button)

        self._content_layout = QVBoxLayout()
        self._outer_layout.addLayout(self._content_layout)

    def set_job(self, job_id: UUID) -> None:
        """Display one job, replacing any previously displayed job."""

        self._job_id = job_id
        self._manual_upload_paths = {}
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
        frame, layout = _card("Project")

        layout.addWidget(QLabel(f"Topic: {job.topic}"))
        layout.addWidget(QLabel(f"Niche: {job.niche}"))
        layout.addWidget(QLabel(f"Platform: {job.platform.value}"))

        self._content_layout.addWidget(frame)

    def _build_workflow_card(self, job: VideoJob) -> None:
        frame, layout = _card("Workflow")

        layout.addWidget(
            QLabel(
                f"Current stage: {job.current_stage.value} | "
                f"Status: {job.status.value}"
            )
        )

        if job.errors:
            errors_label = QLabel(
                "Errors:\n" + "\n".join(f"- {error}" for error in job.errors)
            )
            errors_label.setWordWrap(True)
            errors_label.setStyleSheet("color: #b40000;")
            layout.addWidget(errors_label)

        if job.warnings:
            warnings_label = QLabel(
                "Warnings:\n" + "\n".join(f"- {warning}" for warning in job.warnings)
            )
            warnings_label.setWordWrap(True)
            warnings_label.setStyleSheet("color: #9a6700;")
            layout.addWidget(warnings_label)

        if job.research is None:
            button = QPushButton("Run research")
            button.clicked.connect(self._handle_run_research)
            layout.addWidget(button)
        elif job.script is None:
            button = QPushButton("Run script")
            button.clicked.connect(self._handle_run_script)
            layout.addWidget(button)
        elif job.originality_review is None:
            button = QPushButton("Run originality review")
            button.clicked.connect(self._handle_run_originality)
            layout.addWidget(button)
        elif not job.scenes:
            button = QPushButton("Plan scenes")
            button.clicked.connect(self._handle_plan_scenes)
            layout.addWidget(button)
        else:
            layout.addWidget(QLabel("Content generation steps are complete."))

        self._content_layout.addWidget(frame)

    def _build_research_card(self, job: VideoJob) -> None:
        frame, layout = _card("Research")

        research = job.research

        if research is not None:
            layout.addWidget(QLabel(f"Status: {research.status.value}"))

            summary = QLabel(research.research_summary)
            summary.setWordWrap(True)
            layout.addWidget(summary)

            if research.claude_review_notes:
                notes = QLabel(
                    "Review notes: " + "; ".join(research.claude_review_notes)
                )
                notes.setWordWrap(True)
                layout.addWidget(notes)
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

            if script.claude_review_notes:
                notes = QLabel("Review notes: " + "; ".join(script.claude_review_notes))
                notes.setWordWrap(True)
                layout.addWidget(notes)
        else:
            layout.addWidget(QLabel("No script yet."))

        self._content_layout.addWidget(frame)

    def _build_originality_card(self, job: VideoJob) -> None:
        frame, layout = _card("Originality review")

        review = job.originality_review

        if review is not None:
            layout.addWidget(QLabel(f"Status: {review.status.value}"))
            layout.addWidget(
                QLabel(
                    f"Originality: {review.originality_score} | "
                    f"Human value: {review.human_value_score} | "
                    f"Hook strength: {review.hook_strength_score}"
                )
            )

            if review.strengths:
                layout.addWidget(QLabel("Strengths: " + ", ".join(review.strengths)))

            if review.weaknesses:
                layout.addWidget(QLabel("Weaknesses: " + ", ".join(review.weaknesses)))

            if review.recommendations:
                layout.addWidget(
                    QLabel("Recommendations: " + ", ".join(review.recommendations))
                )
        else:
            layout.addWidget(QLabel("Not reviewed yet."))

        self._content_layout.addWidget(frame)

    def _build_scenes_card(self, job: VideoJob) -> None:
        frame, layout = _card(f"Scenes ({len(job.scenes)})")

        if job.scenes:
            for scene in job.scenes:
                scene_label = QLabel(
                    f"#{scene.scene_number} {scene.title} "
                    f"({scene.estimated_duration_seconds}s): "
                    f"{scene.narration}"
                )
                scene_label.setWordWrap(True)
                layout.addWidget(scene_label)
        else:
            layout.addWidget(QLabel("No scenes planned yet."))

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
        elif job.script is not None and job.script.status.value == "approved":
            layout.addWidget(QLabel("Not generated yet."))

            audience_input = QLineEdit("General audience")
            layout.addWidget(audience_input)

            generate_button = QPushButton("Generate SEO package")
            generate_button.clicked.connect(
                lambda: self._handle_generate_seo(audience_input.text()),
            )
            layout.addWidget(generate_button)
        else:
            layout.addWidget(QLabel("Requires an approved script."))

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
        elif job.script is not None and job.script.status.value == "approved":
            layout.addWidget(QLabel("Not generated yet."))

            audience_input = QLineEdit("General audience")
            layout.addWidget(audience_input)

            generate_button = QPushButton("Generate thumbnail")
            generate_button.clicked.connect(
                lambda: self._handle_generate_thumbnail(audience_input.text()),
            )
            layout.addWidget(generate_button)
        else:
            layout.addWidget(QLabel("Requires an approved script."))

        self._content_layout.addWidget(frame)

    def _build_render_card(self, job: VideoJob) -> None:
        frame, layout = _card("Render")

        assert self._job_id is not None

        waiting_scene_numbers = [
            state.scene_number
            for state in job.scene_asset_states
            if state.requires_user_decision
        ]

        render_result = self._job_store.get_render_result(self._job_id)

        if waiting_scene_numbers:
            note = QLabel(
                "These scenes need a manual video upload before render "
                "can continue - no stock-footage source is configured."
            )
            note.setWordWrap(True)
            layout.addWidget(note)

            for scene_number in waiting_scene_numbers:
                chosen_path = self._manual_upload_paths.get(scene_number)

                scene_label = QLabel(
                    f"Scene {scene_number}: {chosen_path or 'No file selected'}"
                )
                scene_label.setWordWrap(True)
                layout.addWidget(scene_label)

                choose_button = QPushButton(f"Choose file for scene {scene_number}")
                choose_button.clicked.connect(
                    lambda checked=False, n=scene_number: (
                        self._handle_choose_manual_upload(n)
                    ),
                )
                layout.addWidget(choose_button)

            submit_button = QPushButton("Submit uploads and continue render")
            submit_button.clicked.connect(self._handle_submit_manual_uploads)
            layout.addWidget(submit_button)
        elif render_result is not None:
            layout.addWidget(
                QLabel(f"Success: {render_result.success}"),
            )
            layout.addWidget(
                QLabel(f"Status: {render_result.status.value}"),
            )

            if render_result.render_result is not None:
                layout.addWidget(
                    QLabel(
                        "Output file: " f"{render_result.render_result.output_file}"
                    ),
                )

            if render_result.errors:
                errors_label = QLabel(
                    "Errors:\n"
                    + "\n".join(f"- {error}" for error in render_result.errors)
                )
                errors_label.setWordWrap(True)
                errors_label.setStyleSheet("color: #b40000;")
                layout.addWidget(errors_label)

            if render_result.warnings:
                warnings_label = QLabel(
                    "Warnings:\n"
                    + "\n".join(f"- {warning}" for warning in render_result.warnings)
                )
                warnings_label.setWordWrap(True)
                warnings_label.setStyleSheet("color: #9a6700;")
                layout.addWidget(warnings_label)

            retry_button = QPushButton("Run render again")
            retry_button.clicked.connect(self._handle_run_render)
            layout.addWidget(retry_button)
        elif job.scenes:
            layout.addWidget(QLabel("Not rendered yet."))

            render_button = QPushButton("Run render")
            render_button.clicked.connect(self._handle_run_render)
            layout.addWidget(render_button)
        else:
            layout.addWidget(QLabel("Requires planned scenes."))

        self._content_layout.addWidget(frame)

    def _build_final_export_card(self, job: VideoJob) -> None:
        frame, layout = _card("Final export")

        assert self._job_id is not None

        final_export = self._job_store.get_final_export(self._job_id)
        render_result = self._job_store.get_render_result(self._job_id)
        seo_package = self._job_store.get_seo_package(self._job_id)
        thumbnail = self._job_store.get_thumbnail(self._job_id)

        if final_export is not None:
            layout.addWidget(
                QLabel(f"Status: {final_export.status.value}"),
            )
            layout.addWidget(
                QLabel(f"Video: {final_export.final_video_path}"),
            )
            layout.addWidget(
                QLabel(f"Export directory: {final_export.export_directory}"),
            )
        elif render_result is not None and render_result.success:
            if seo_package is not None and thumbnail is not None:
                layout.addWidget(QLabel("Not built yet."))

                export_button = QPushButton("Build final export package")
                export_button.clicked.connect(self._handle_build_final_export)
                layout.addWidget(export_button)
            else:
                layout.addWidget(
                    QLabel("Requires an SEO package and a thumbnail."),
                )
        else:
            layout.addWidget(QLabel("Requires a successful render."))

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
        self.refresh()

    def _handle_submit_manual_uploads(self) -> None:
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
        ]

        if missing_scene_numbers:
            self._record_error(
                job,
                "Choose a file for every scene before submitting: "
                + ", ".join(str(number) for number in missing_scene_numbers),
            )

            return

        asset_decisions = [
            {
                "scene_number": scene_number,
                "decision": "manual_upload",
                "manual_upload_path": self._manual_upload_paths[scene_number],
                "project_id": job.project_name,
            }
            for scene_number in waiting_scene_numbers
        ]

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

    def _record_error(self, job: VideoJob, message: str) -> None:
        job.errors.append(message)
        QMessageBox.warning(self, "Step failed", message)
        self.refresh()
