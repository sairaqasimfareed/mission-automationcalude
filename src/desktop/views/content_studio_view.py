from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.desktop.job_store import JobStore
from src.desktop.widgets import badge, button, card, muted, small_muted, status_label
from src.models.enums import Platform, ProductionMode, WorkflowStage
from src.models.video_job import VideoJob
from src.services.content_pipeline import ContentPipeline
from src.services.genre_profile_registry_service import (
    GenreProfileRegistryService,
)

_LEFT = Qt.AlignmentFlag.AlignLeft

_GENRE_IDS = [
    profile.genre_id
    for profile in GenreProfileRegistryService.with_default_profiles().list_all()
]


class ContentStudioView(QWidget):
    """
    Content Studio: research, script, originality review, scene
    planning.

    Each step runs as a separate, explicitly triggered action rather
    than one atomic call, so current stage and progress stay genuinely
    observable instead of hidden inside ContentPipeline.run(). Each
    step delegates to the same ContentPipeline sub-components
    ContentPipeline.run() itself sequences, so no business logic is
    duplicated here - only the UI-facing sequencing.
    """

    def __init__(
        self,
        *,
        job_store: JobStore,
        content_pipeline: ContentPipeline,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__()

        self._job_store = job_store
        self._content_pipeline = content_pipeline
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

        self._build_settings_card(job)
        self._build_workflow_card(job)
        self._build_research_card(job)
        self._build_script_card(job)
        self._build_originality_card(job)
        self._build_scenes_card(job)

    def _build_settings_card(self, job: VideoJob) -> None:
        frame, layout = card("Project settings", icon_name="settings")

        form = QFormLayout()
        form.setSpacing(8)

        genre_select = QComboBox()
        genre_select.addItems(_GENRE_IDS)

        if job.genre_id in _GENRE_IDS:
            genre_select.setCurrentIndex(_GENRE_IDS.index(job.genre_id))

        form.addRow("Genre", genre_select)

        platform_select = QComboBox()
        platform_select.addItems([platform.value for platform in Platform])
        platform_select.setCurrentText(job.platform.value)
        form.addRow("Platform", platform_select)

        production_mode_select = QComboBox()
        production_mode_select.addItems([mode.value for mode in ProductionMode])
        production_mode_select.setCurrentText(job.production_mode.value)
        form.addRow("Production mode", production_mode_select)

        language_input = QLineEdit(job.language)
        form.addRow("Language", language_input)

        target_country_input = QLineEdit(job.target_country)
        form.addRow("Target country", target_country_input)

        layout.addLayout(form)

        save_button = button("Save settings", variant="primary", icon_name="check")
        save_button.clicked.connect(
            lambda: self._handle_save_settings(
                genre_select=genre_select,
                platform_select=platform_select,
                production_mode_select=production_mode_select,
                language_input=language_input,
                target_country_input=target_country_input,
            )
        )
        layout.addWidget(save_button, alignment=_LEFT)

        self._layout.addWidget(frame)

    def _build_workflow_card(self, job: VideoJob) -> None:
        frame, layout = card("Content workflow", icon_name="dashboard")

        layout.addWidget(badge(f"{job.current_stage.value} · {job.status.value}"))

        if job.errors:
            layout.addWidget(
                status_label(
                    "Errors:\n" + "\n".join(f"- {error}" for error in job.errors),
                    role="error",
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

        self._layout.addWidget(frame)

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

        self._layout.addWidget(frame)

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

        self._layout.addWidget(frame)

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

        self._layout.addWidget(frame)

    def _build_scenes_card(self, job: VideoJob) -> None:
        frame, layout = card(f"Scenes ({len(job.scenes)})", icon_name="clapper")

        if job.scenes:
            layout.addWidget(
                small_muted(
                    "Full scene detail, per-scene duration, and resolved "
                    "clips live in the Clip Workspace."
                )
            )

            for scene in job.scenes:
                layout.addWidget(
                    small_muted(
                        f"#{scene.scene_number} {scene.title} "
                        f"({scene.estimated_duration_seconds}s)"
                    )
                )
        else:
            layout.addWidget(small_muted("No scenes planned yet."))

        self._layout.addWidget(frame)

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
        self._on_change()

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
        self._on_change()

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
        self._on_change()

    def _handle_save_settings(
        self,
        *,
        genre_select: QComboBox,
        platform_select: QComboBox,
        production_mode_select: QComboBox,
        language_input: QLineEdit,
        target_country_input: QLineEdit,
    ) -> None:
        job = self._current_job()

        if job is None:
            return

        try:
            job.genre_id = genre_select.currentText()
            job.platform = Platform(platform_select.currentText())
            job.production_mode = ProductionMode(production_mode_select.currentText())
            job.language = language_input.text()
            job.target_country = target_country_input.text()
        except ValueError as error:
            self._record_error(job, f"Could not save project settings: {error}")

            return

        self._on_change()

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
        self._on_change()

    def _current_job(self) -> VideoJob | None:
        if self._job_id is None:
            return None

        return self._job_store.get(self._job_id)

    def _record_error(self, job: VideoJob, message: str) -> None:
        job.errors.append(message)
        QMessageBox.warning(self, "Step failed", message)
        self._on_change()
