from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.desktop.job_store import JobStore
from src.desktop.widgets import (
    badge,
    button,
    card,
    muted,
    separator,
    small_muted,
    status_label,
)
from src.models.approval import ApprovalPolicyConfig, HumanApprovalAction
from src.models.enums import Platform, ProductionMode, WorkflowStage
from src.models.video_job import VideoJob
from src.services.approval_gate_service import ApprovalGateService
from src.services.content_intelligence_pipeline import ContentIntelligencePipeline
from src.services.content_pipeline import ContentPipeline
from src.services.genre_profile_registry_service import (
    GenreProfileRegistryService,
)

_LEFT = Qt.AlignmentFlag.AlignLeft

_GENRE_IDS = [
    profile.genre_id
    for profile in GenreProfileRegistryService.with_default_profiles().list_all()
]

# Named presets a user picks from, rather than editing 11 individual
# AUTO/REVIEW/MANUAL fields by hand - per-decision-point overrides
# remain possible via ApprovalPolicyConfig directly, just not through
# this settings panel yet.
_APPROVAL_MODE_PRESETS: dict[str, Callable[[], ApprovalPolicyConfig]] = {
    "Fully Automatic": ApprovalPolicyConfig.full_auto,
    "Custom Approval": ApprovalPolicyConfig.review_critical_stages,
    "Approve Every Step": ApprovalPolicyConfig.manual_editorial,
}


_APPROVAL_FIELDS_TO_COMPARE = {"id", "created_at", "updated_at"}


def _approval_mode_label(policy: ApprovalPolicyConfig) -> str:
    """
    Return the preset label matching one policy, or "Custom Approval"
    as a safe fallback for a hand-edited policy that does not match
    any of the three named presets exactly.

    Compares only the AUTO/REVIEW/MANUAL fields - every
    ApprovalPolicyConfig also carries its own id/created_at/
    updated_at (MissionBaseModel), which would make two otherwise-
    identical policies compare unequal by plain `==`.
    """

    policy_fields = policy.model_dump(exclude=_APPROVAL_FIELDS_TO_COMPARE)

    for label, factory in _APPROVAL_MODE_PRESETS.items():
        preset_fields = factory().model_dump(exclude=_APPROVAL_FIELDS_TO_COMPARE)

        if policy_fields == preset_fields:
            return label

    return "Custom Approval"


# (stage key, display label) in pipeline order. Each stage gets its
# own dedicated panel - selecting one shows only that stage's content
# at full width instead of every artifact competing for space in one
# long scroll.
_CI_STAGES: list[tuple[str, str]] = [
    ("audience_promise", "Audience promise"),
    ("research_plan", "Research plan"),
    ("research", "Research"),
    ("story_angles", "Story angles"),
    ("narrative_architecture", "Narrative architecture"),
    ("retention_audit", "Retention audit"),
    ("hooks", "Hooks"),
    ("script", "Script"),
    ("continuity_bible", "Continuity bible"),
    ("editorial_critique", "Editorial critique"),
    ("quality_gate", "Quality gate"),
    ("revision", "Revision"),
    ("packaging_hypothesis", "Packaging hypothesis"),
    ("scene_planning", "Scene planning"),
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
        content_intelligence_pipeline: ContentIntelligencePipeline,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__()

        self._job_store = job_store
        self._content_pipeline = content_pipeline
        self._content_intelligence_pipeline = content_intelligence_pipeline
        self._on_change = on_change
        self._job_id: UUID | None = None
        self._selected_ci_stage_index = 0

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
        self._build_content_intelligence_card(job)
        self._build_approval_history_card(job)
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

        approval_mode_select = QComboBox()
        approval_mode_select.addItems(list(_APPROVAL_MODE_PRESETS))
        approval_mode_select.setCurrentText(_approval_mode_label(job.approval_policy))
        form.addRow("Approval mode", approval_mode_select)

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
                approval_mode_select=approval_mode_select,
                language_input=language_input,
                target_country_input=target_country_input,
            )
        )
        layout.addWidget(save_button, alignment=_LEFT)

        self._layout.addWidget(frame)

    def _build_content_intelligence_card(self, job: VideoJob) -> None:
        frame, layout = card("Content Intelligence Engine", icon_name="dashboard")

        layout.addWidget(
            small_muted(
                "Genre-aware research, story, and script planning - runs "
                "alongside the workflow below, not in place of it."
            )
        )

        stage_row = QHBoxLayout()
        stage_row.setSpacing(6)

        for index, (_key, label) in enumerate(_CI_STAGES):
            is_selected = index == self._selected_ci_stage_index
            stage_button = button(label, variant="primary" if is_selected else "ghost")
            stage_button.clicked.connect(
                lambda _checked=False, i=index: self._handle_select_ci_stage(i)
            )
            stage_row.addWidget(stage_button)

        stage_row.addStretch()
        layout.addLayout(stage_row)
        layout.addWidget(separator())

        stage_key, stage_label = _CI_STAGES[self._selected_ci_stage_index]
        self._build_ci_stage_panel(layout, job, stage_key, stage_label)

        self._layout.addWidget(frame)

    def _build_ci_stage_panel(
        self,
        layout: QVBoxLayout,
        job: VideoJob,
        stage_key: str,
        stage_label: str,
    ) -> None:
        builders: dict[str, Callable[[QVBoxLayout, VideoJob], bool]] = {
            "audience_promise": self._render_audience_promise_panel,
            "research_plan": self._render_research_plan_panel,
            "research": self._render_ci_research_panel,
            "story_angles": self._render_story_angles_panel,
            "narrative_architecture": self._render_narrative_architecture_panel,
            "retention_audit": self._render_retention_audit_panel,
            "hooks": self._render_hooks_panel,
            "script": self._render_ci_script_panel,
            "continuity_bible": self._render_continuity_bible_panel,
            "editorial_critique": self._render_editorial_critique_panel,
            "quality_gate": self._render_quality_gate_panel,
            "revision": self._render_revision_panel,
            "packaging_hypothesis": self._render_packaging_hypothesis_panel,
            "scene_planning": self._render_scene_planning_panel,
        }

        can_run = builders[stage_key](layout, job)

        run_button = button(
            f"Run {stage_label.lower()}", variant="primary", icon_name="research"
        )
        run_button.setEnabled(can_run)
        run_button.clicked.connect(lambda: self._handle_run_ci_stage(stage_key))
        layout.addWidget(run_button, alignment=_LEFT)

    def _build_approval_history_card(self, job: VideoJob) -> None:
        frame, layout = card("Approval history", icon_name="shield")

        if not job.content_decisions:
            layout.addWidget(small_muted("No approval decisions recorded yet."))
            self._layout.addWidget(frame)

            return

        pending = ApprovalGateService.latest_pending(job)

        for record in reversed(job.content_decisions):
            approval = record.approval
            state_text = approval.state.value if approval is not None else "unknown"
            layout.addWidget(badge(f"{record.stage} · {state_text}"))
            layout.addWidget(small_muted(record.summary))

            if approval is not None and approval.confidence is not None:
                layout.addWidget(small_muted(f"Confidence: {approval.confidence:.2f}"))

        if pending is not None:
            layout.addWidget(separator())
            layout.addWidget(
                small_muted(
                    f"'{pending.stage}' is waiting on a human decision "
                    f"('{pending.approval.decision_point}')."
                    if pending.approval is not None
                    else f"'{pending.stage}' is waiting on a human decision."
                )
            )

            button_row = QHBoxLayout()
            button_row.setSpacing(6)

            approve_button = button("Approve", variant="primary", icon_name="check")
            approve_button.clicked.connect(
                lambda: self._handle_resolve_approval(HumanApprovalAction.APPROVE)
            )
            button_row.addWidget(approve_button)

            reject_button = button("Reject", variant="ghost")
            reject_button.clicked.connect(
                lambda: self._handle_resolve_approval(HumanApprovalAction.REJECT)
            )
            button_row.addWidget(reject_button)

            button_row.addStretch()
            layout.addLayout(button_row)

        self._layout.addWidget(frame)

    def _handle_resolve_approval(self, action: HumanApprovalAction) -> None:
        job = self._current_job()

        if job is None:
            return

        pending = ApprovalGateService.latest_pending(job)

        if pending is None or pending.approval is None:
            return

        try:
            self._content_intelligence_pipeline.resolve_approval(
                job, pending.approval.decision_point, action
            )
        except ValueError as error:
            self._record_error(job, f"Could not resolve approval decision: {error}")

            return

        self._on_change()

    def _render_audience_promise_panel(
        self, layout: QVBoxLayout, job: VideoJob
    ) -> bool:
        promise = job.audience_promise

        if promise is None:
            layout.addWidget(small_muted("Not started."))

            return True

        layout.addWidget(badge(promise.promise_strength.value))
        layout.addWidget(muted(f"Central curiosity: {promise.central_curiosity}"))
        layout.addWidget(muted(f"Primary question: {promise.primary_question}"))
        layout.addWidget(muted(f"Expected payoff: {promise.expected_payoff}"))

        if promise.weakness_reasons:
            layout.addWidget(
                small_muted("Weaknesses: " + ", ".join(promise.weakness_reasons))
            )

        return True

    def _render_research_plan_panel(self, layout: QVBoxLayout, job: VideoJob) -> bool:
        plan = job.research_plan

        if plan is None:
            layout.addWidget(
                small_muted(
                    "Not started."
                    if job.audience_promise is not None
                    else "Requires an audience promise first."
                )
            )

            return job.audience_promise is not None

        for question in plan.research_questions:
            layout.addWidget(small_muted(f"- {question}"))

        return True

    def _render_ci_research_panel(self, layout: QVBoxLayout, job: VideoJob) -> bool:
        research = job.research

        if research is None:
            layout.addWidget(small_muted("Not started."))

            return True

        layout.addWidget(badge(research.status.value))
        layout.addWidget(muted(research.research_summary))

        return True

    def _render_story_angles_panel(self, layout: QVBoxLayout, job: VideoJob) -> bool:
        if not job.story_angles:
            can_run = job.research is not None and job.audience_promise is not None
            layout.addWidget(
                small_muted(
                    "Not started."
                    if can_run
                    else "Requires research and an audience promise first."
                )
            )

            return can_run

        evaluations_by_title = {
            evaluation.angle_title: evaluation
            for evaluation in job.story_angle_evaluations
        }
        selected_title = (
            job.selected_story_angle.title if job.selected_story_angle else None
        )

        for angle in job.story_angles:
            is_selected = angle.title == selected_title
            evaluation = evaluations_by_title.get(angle.title)
            score_text = (
                f" · score {evaluation.overall_score:.0f}"
                if evaluation is not None
                else ""
            )

            layout.addWidget(
                badge(f"{angle.style.value}{' · selected' if is_selected else ''}")
            )
            layout.addWidget(muted(f"{angle.title}{score_text}"))
            layout.addWidget(small_muted(angle.description))

        return True

    def _render_narrative_architecture_panel(
        self, layout: QVBoxLayout, job: VideoJob
    ) -> bool:
        if job.story_blueprint is None:
            can_run = job.selected_story_angle is not None
            layout.addWidget(
                small_muted(
                    "Not started."
                    if can_run
                    else "Requires a selected story angle first."
                )
            )

            return can_run

        for beat in sorted(job.story_blueprint.beats, key=lambda b: b.start_seconds):
            layout.addWidget(
                small_muted(
                    f"[{beat.beat_type.value}] {beat.start_seconds:.0f}s-"
                    f"{beat.end_seconds:.0f}s · tension {beat.tension_level} · "
                    f"{beat.purpose}"
                )
            )

        if job.reveal_map is not None:
            layout.addWidget(
                small_muted(
                    f"{len(job.reveal_map.curiosity_loops)} curiosity loop(s), "
                    f"{len(job.reveal_map.reveals)} reveal(s) planned."
                )
            )

        return True

    def _render_retention_audit_panel(self, layout: QVBoxLayout, job: VideoJob) -> bool:
        report = job.retention_audit

        if report is None:
            can_run = job.story_blueprint is not None
            layout.addWidget(
                small_muted(
                    "Not started." if can_run else "Requires a story blueprint first."
                )
            )

            return can_run

        layout.addWidget(badge("passed" if report.passed else "findings"))
        layout.addWidget(
            small_muted(
                f"{report.reveal_count} reveal-type beat(s) "
                f"(genre expects at least {report.expected_minimum_reveal_count})."
            )
        )

        for finding in report.findings:
            layout.addWidget(
                small_muted(f"[{finding.issue_type.value}] {finding.description}")
            )

        return True

    def _render_hooks_panel(self, layout: QVBoxLayout, job: VideoJob) -> bool:
        if not job.hook_candidates:
            can_run = job.story_blueprint is not None
            layout.addWidget(
                small_muted(
                    "Not started." if can_run else "Requires a story blueprint first."
                )
            )

            return can_run

        evaluations_by_text = {
            evaluation.hook_text: evaluation for evaluation in job.hook_evaluations
        }
        selected_text = job.selected_hook.hook_text if job.selected_hook else None

        for hook in job.hook_candidates:
            evaluation = evaluations_by_text.get(hook.text)
            is_selected = hook.text == selected_text
            tag = (
                "selected"
                if is_selected
                else ("rejected" if evaluation and evaluation.rejected else None)
            )
            score_text = (
                f" · score {evaluation.overall_score:.0f}"
                if evaluation is not None
                else ""
            )

            if tag is not None:
                layout.addWidget(badge(tag))

            layout.addWidget(small_muted(f"{hook.text}{score_text}"))

        if job.re_hook_plan is not None:
            for re_hook in job.re_hook_plan.re_hooks:
                layout.addWidget(
                    small_muted(
                        f"Re-hook @ {re_hook.position_seconds:.0f}s "
                        f"[{re_hook.re_hook_type.value}]: {re_hook.text}"
                    )
                )

        return True

    def _render_ci_script_panel(self, layout: QVBoxLayout, job: VideoJob) -> bool:
        script = job.generated_script

        if script is None:
            can_run = job.selected_hook is not None
            layout.addWidget(
                small_muted(
                    "Not started." if can_run else "Requires a selected hook first."
                )
            )

            return can_run

        layout.addWidget(
            badge(f"{len(script.segments)} segments · {script.word_count} words")
        )
        layout.addWidget(muted(script.full_narration))

        return True

    def _render_continuity_bible_panel(
        self, layout: QVBoxLayout, job: VideoJob
    ) -> bool:
        bible = job.continuity_bible

        if bible is None:
            can_run = job.generated_script is not None
            layout.addWidget(
                small_muted(
                    "Not started." if can_run else "Requires a generated script first."
                )
            )

            return can_run

        validation = job.continuity_validation
        layout.addWidget(
            badge(
                f"{len(bible.entries)} entries · "
                + (
                    "consistent"
                    if validation and validation.is_consistent
                    else "flagged"
                )
            )
        )

        for entry in bible.entries:
            layout.addWidget(
                small_muted(
                    f"[{entry.entry_type.value}] {entry.name} "
                    f"(seg {entry.first_mentioned_segment}): {entry.description}"
                )
            )

        if validation is not None:
            for inconsistency in validation.inconsistencies:
                layout.addWidget(
                    status_label(
                        f"'{inconsistency.name}' differs between segment "
                        f"{inconsistency.first_segment} "
                        f"('{inconsistency.first_description}') and segment "
                        f"{inconsistency.later_segment} "
                        f"('{inconsistency.later_description}') - worth reviewing.",
                        role="warning",
                    )
                )

        return True

    def _render_editorial_critique_panel(
        self, layout: QVBoxLayout, job: VideoJob
    ) -> bool:
        critique = job.editorial_critique

        if critique is None:
            can_run = job.generated_script is not None
            layout.addWidget(
                small_muted(
                    "Not started." if can_run else "Requires a generated script first."
                )
            )

            return can_run

        for dimension, score in sorted(critique.dimension_scores.items()):
            layout.addWidget(small_muted(f"{dimension}: {score}"))

        if not critique.findings:
            layout.addWidget(status_label("No problems found.", role="success"))
        else:
            for finding in critique.findings:
                location = (
                    f"segment {finding.segment_number}"
                    if finding.segment_number is not None
                    else "whole script"
                )
                layout.addWidget(badge(f"{finding.severity.value} · {location}"))
                layout.addWidget(
                    small_muted(
                        f"{finding.problem} -> {finding.recommended_correction}"
                    )
                )

        return True

    def _render_quality_gate_panel(self, layout: QVBoxLayout, job: VideoJob) -> bool:
        report = job.script_quality_report

        if report is None:
            can_run = job.editorial_critique is not None
            layout.addWidget(
                small_muted(
                    "Not started."
                    if can_run
                    else "Requires an editorial critique first."
                )
            )

            return can_run

        layout.addWidget(badge(report.status.value))

        for dimension, threshold in sorted(report.dimension_thresholds.items()):
            score = report.dimension_scores.get(dimension, 0)
            passed = dimension not in report.failed_dimensions
            layout.addWidget(
                small_muted(
                    f"{'[pass]' if passed else '[fail]'} {dimension}: "
                    f"{score} (needs {threshold})"
                )
            )

        if report.blocking_findings:
            layout.addWidget(
                small_muted(f"{len(report.blocking_findings)} blocking finding(s).")
            )

        return True

    def _render_revision_panel(self, layout: QVBoxLayout, job: VideoJob) -> bool:
        self._render_script_version_history(layout, job)

        critique = job.editorial_critique

        if critique is None or not critique.findings:
            layout.addWidget(
                small_muted(
                    "Nothing to revise - run the editorial critique first and "
                    "confirm it raised at least one finding."
                )
            )

            return False

        history = job.script_version_history

        if history is not None and history.is_locked:
            layout.addWidget(
                small_muted(
                    f"Version {history.current_version.version_number} is "
                    "locked - unlock it above before revising."
                )
            )

            return False

        layout.addWidget(
            small_muted(
                f"Revising will address {len(critique.findings)} finding(s) and "
                "clear the current critique and quality report, since both "
                "describe the script before revision."
            )
        )

        return True

    def _render_script_version_history(
        self, layout: QVBoxLayout, job: VideoJob
    ) -> None:
        history = job.script_version_history

        if history is None:
            return

        layout.addWidget(badge(f"{len(history.versions)} version(s)"))

        for version in sorted(history.versions, key=lambda v: v.version_number):
            change = version.change_class.value if version.change_class else "initial"
            lock_tag = " [locked]" if version.locked else ""
            layout.addWidget(
                small_muted(
                    f"v{version.version_number} [{change}]{lock_tag}: "
                    f"{version.change_summary}"
                )
            )

        current = history.current_version
        lock_button = button(
            "Unlock current version" if current.locked else "Lock current version",
            variant="ghost",
        )
        lock_button.clicked.connect(self._handle_toggle_script_version_lock)
        layout.addWidget(lock_button, alignment=_LEFT)
        layout.addWidget(separator())

    def _render_packaging_hypothesis_panel(
        self, layout: QVBoxLayout, job: VideoJob
    ) -> bool:
        hypothesis = job.packaging_hypothesis

        if hypothesis is None:
            can_run = job.generated_script is not None and job.selected_hook is not None
            layout.addWidget(
                small_muted(
                    "Not started."
                    if can_run
                    else "Requires a generated script and a selected hook first."
                )
            )

            return can_run

        layout.addWidget(muted(f"Viewer promise: {hypothesis.viewer_promise}"))
        layout.addWidget(
            small_muted(
                "Title territories: " + " | ".join(hypothesis.title_territories)
            )
        )
        layout.addWidget(
            small_muted(
                "Thumbnail concepts: " + " | ".join(hypothesis.thumbnail_concepts)
            )
        )
        layout.addWidget(
            small_muted(f"Curiosity mechanism: {hypothesis.curiosity_mechanism}")
        )
        layout.addWidget(
            small_muted(f"Expected emotion: {hypothesis.expected_emotion}")
        )
        layout.addWidget(
            small_muted(f"Differentiation angle: {hypothesis.differentiation_angle}")
        )

        return True

    def _render_scene_planning_panel(self, layout: QVBoxLayout, job: VideoJob) -> bool:
        if not job.scenes:
            can_run = job.generated_script is not None
            layout.addWidget(
                small_muted(
                    "Not started." if can_run else "Requires a generated script first."
                )
            )

            return can_run

        layout.addWidget(badge(f"{len(job.scenes)} scene(s)"))

        for scene in job.scenes:
            tag = scene.narrative_function or "legacy"
            layout.addWidget(
                small_muted(
                    f"[{tag}] {scene.title} · {scene.estimated_duration_seconds}s · "
                    f"{scene.camera_direction}"
                )
            )

        return True

    def _handle_select_ci_stage(self, index: int) -> None:
        self._selected_ci_stage_index = index
        job = self._current_job()

        if job is not None:
            self.refresh(job)

    def _handle_run_ci_stage(self, stage_key: str) -> None:
        job = self._current_job()

        if job is None:
            return

        runners: dict[str, Callable[[VideoJob], VideoJob]] = {
            "audience_promise": self._content_intelligence_pipeline.run_audience_promise,
            "research_plan": self._content_intelligence_pipeline.run_research_plan,
            "research": self._content_intelligence_pipeline.run_research,
            "story_angles": self._content_intelligence_pipeline.run_story_angles,
            "narrative_architecture": (
                self._content_intelligence_pipeline.run_narrative_architecture
            ),
            "retention_audit": self._content_intelligence_pipeline.run_retention_audit,
            "hooks": self._content_intelligence_pipeline.run_hooks,
            "script": self._content_intelligence_pipeline.run_script,
            "continuity_bible": self._content_intelligence_pipeline.run_continuity_bible,
            "editorial_critique": (
                self._content_intelligence_pipeline.run_editorial_critique
            ),
            "quality_gate": self._content_intelligence_pipeline.run_quality_gate,
            "revision": self._content_intelligence_pipeline.run_revision,
            "packaging_hypothesis": (
                self._content_intelligence_pipeline.run_packaging_hypothesis
            ),
            "scene_planning": self._content_intelligence_pipeline.run_scene_planning,
        }

        try:
            runners[stage_key](job)
        except (RuntimeError, ValueError) as error:
            self._record_error(job, f"Content Intelligence stage failed: {error}")

            return

        self._on_change()

    def _handle_toggle_script_version_lock(self) -> None:
        job = self._current_job()

        if job is None or job.script_version_history is None:
            return

        history = job.script_version_history
        current = history.current_version
        service = self._content_intelligence_pipeline.script_version_service

        try:
            if current.locked:
                job.script_version_history = service.unlock_version(
                    history=history, version_number=current.version_number
                )
            else:
                job.script_version_history = service.lock_version(
                    history=history, version_number=current.version_number
                )
        except ValueError as error:
            self._record_error(job, f"Could not update script version lock: {error}")

            return

        self._on_change()

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
        approval_mode_select: QComboBox,
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
            job.approval_policy = _APPROVAL_MODE_PRESETS[
                approval_mode_select.currentText()
            ]()
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
