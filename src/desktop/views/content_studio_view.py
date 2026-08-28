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
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.desktop.approval_mode_labels import (
    APPROVAL_MODE_PRESETS as _APPROVAL_MODE_PRESETS,
)
from src.desktop.approval_mode_labels import (
    approval_mode_label as _approval_mode_label,
)
from src.desktop.job_store import JobStore
from src.desktop.recovery_dialog import show_recoverable_error
from src.desktop.widgets import (
    badge,
    button,
    card,
    muted,
    separator,
    small_muted,
    status_label,
)
from src.models.approval import HumanApprovalAction
from src.models.artifact_lifecycle import ArtifactType
from src.models.creative_direction import CreativeDirection
from src.models.enums import Platform, ProductionMode, WorkflowStage
from src.models.reviewer_result import ReviewerResult
from src.models.story_angle import StoryAngle, StoryAngleStyle
from src.models.topic_candidate import TopicCandidate
from src.models.video_job import VideoJob
from src.services.approval_gate_service import ApprovalGateService
from src.services.content_intelligence_pipeline import ContentIntelligencePipeline
from src.services.content_pipeline import ContentPipeline
from src.services.content_studio_journey_service import (
    ContentStudioJourneyService,
    JourneyCheckpointStatus,
)
from src.services.genre_profile_registry_service import (
    GenreProfileRegistryService,
)
from src.services.reviewer_service import ReviewerService
from src.services.topic_candidate_generation_service import (
    TopicCandidateGenerationService,
)

_LEFT = Qt.AlignmentFlag.AlignLeft

_GENRE_IDS = [
    profile.genre_id
    for profile in GenreProfileRegistryService.with_default_profiles().list_all()
]


_JOURNEY_STATUS_ROLE: dict[JourneyCheckpointStatus, str | None] = {
    JourneyCheckpointStatus.NOT_STARTED: None,
    JourneyCheckpointStatus.WAITING: "warning",
    JourneyCheckpointStatus.NEEDS_REVISION: "warning",
    JourneyCheckpointStatus.APPROVED: "success",
}

_JOURNEY_STATUS_LABEL: dict[JourneyCheckpointStatus, str] = {
    JourneyCheckpointStatus.NOT_STARTED: "Not started",
    JourneyCheckpointStatus.WAITING: "Waiting",
    JourneyCheckpointStatus.NEEDS_REVISION: "Needs revision",
    JourneyCheckpointStatus.APPROVED: "Approved",
}

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

# Maps each of the 14 granular CI stages onto the nearest of the 9
# canonical ArtifactType values (Content Studio Redesign, Phase 4) and
# the VideoJob field holding that stage's current artifact - lets one
# generic "Review this stage" action work across every stage rather
# than needing its own reviewer wiring per stage.
_CI_STAGE_REVIEW_TARGET: dict[str, tuple[ArtifactType, str]] = {
    "audience_promise": (ArtifactType.AUDIENCE_STRATEGY, "audience_promise"),
    "research_plan": (ArtifactType.RESEARCH_BRIEF, "research_plan"),
    "research": (ArtifactType.RESEARCH, "research"),
    "story_angles": (ArtifactType.CREATIVE_DIRECTION, "selected_story_angle"),
    "narrative_architecture": (ArtifactType.STORY_ARCHITECTURE, "story_blueprint"),
    "retention_audit": (ArtifactType.STORY_ARCHITECTURE, "retention_audit"),
    "hooks": (ArtifactType.HOOK, "selected_hook"),
    "script": (ArtifactType.SCRIPT, "generated_script"),
    "continuity_bible": (ArtifactType.STORY_ARCHITECTURE, "continuity_bible"),
    "editorial_critique": (ArtifactType.SCRIPT, "editorial_critique"),
    "quality_gate": (ArtifactType.QUALITY_GATE, "script_quality_report"),
    "revision": (ArtifactType.SCRIPT, "generated_script"),
    "packaging_hypothesis": (ArtifactType.SCRIPT, "packaging_hypothesis"),
    "scene_planning": (ArtifactType.SCRIPT, "scenes"),
}


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
        reviewer_service: ReviewerService,
        topic_candidate_generation_service: TopicCandidateGenerationService,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__()

        self._job_store = job_store
        self._content_pipeline = content_pipeline
        self._content_intelligence_pipeline = content_intelligence_pipeline
        self._reviewer_service = reviewer_service
        self._topic_candidate_generation_service = topic_candidate_generation_service
        self._journey_service = ContentStudioJourneyService()
        self._on_change = on_change
        self._job_id: UUID | None = None
        self._selected_ci_stage_index = 0

        # Transient - a review is a read-only critique, never persisted
        # to VideoJob (the Reviewer never becomes the author). Keyed by
        # stage_key so switching stages doesn't lose a prior result,
        # cleared only when set_job() moves to a different project.
        self._last_review_by_stage: dict[str, ReviewerResult] = {}

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
        self._last_review_by_stage = {}

    def refresh(self, job: VideoJob) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)

            if item is None:
                continue

            widget = item.widget()

            if widget is not None:
                widget.deleteLater()

        self._build_journey_card(job)
        self._build_topic_card(job)
        self._build_settings_card(job)
        self._build_content_intelligence_card(job)
        self._build_approval_history_card(job)
        self._build_workflow_card(job)
        self._build_research_card(job)
        self._build_script_card(job)
        self._build_originality_card(job)
        self._build_scenes_card(job)

    def _build_journey_card(self, job: VideoJob) -> None:
        """
        Content Studio Redesign, Phase 3: a condensed, at-a-glance
        strip over ContentIntelligencePipeline's 14 granular stages -
        Audience/Research/Angle/Story/Hook/Script/Quality/Script Lock,
        in the order they actually run (not the redesign document's
        own listed order - research runs before angle selection here,
        so showing Angle first would misrepresent the real pipeline).
        Purely a read-only overview; every checkpoint's underlying
        artifact is still edited through its own stage panel below.
        """

        frame, layout = card("Production journey", icon_name="dashboard")

        strip = QHBoxLayout()
        strip.setSpacing(10)

        for checkpoint in self._journey_service.compute(job):
            role = _JOURNEY_STATUS_ROLE[checkpoint.status]
            text = f"{checkpoint.label}: {_JOURNEY_STATUS_LABEL[checkpoint.status]}"

            if role is None:
                strip.addWidget(small_muted(text))
            else:
                strip.addWidget(status_label(text, role=role))

        strip.addStretch()
        layout.addLayout(strip)

        self._layout.addWidget(frame)

    def _build_topic_card(self, job: VideoJob) -> None:
        """
        Content Studio Redesign, Phase 5: Topic Intelligence Workspace.

        Deliberately a standalone panel, not one of the _CI_STAGES
        rotation - Topic precedes AudienceProfile/ChannelStyleProfile
        (nothing to compose an EditorialProfile from yet at this
        point), and selecting a candidate here does not change
        `job.topic` itself or feed ContentIntelligencePipeline.run_all()
        - that full pipeline-sequencing change is out of scope for this
        phase (see the honest-scoping note on VideoJob.topic_candidates).
        This panel only lets a project explore and record scored topic
        alternatives to the seed idea already typed at project creation.
        """

        frame, layout = card("Topic intelligence", icon_name="research")

        layout.addWidget(
            small_muted(
                f"Seed idea: {job.topic}\n"
                "Generate scored topic alternatives, or enter your own."
            )
        )

        if job.selected_topic_candidate is not None:
            selected = job.selected_topic_candidate
            label = "Custom topic" if selected.is_custom else "Selected topic"
            layout.addWidget(status_label(f"{label}: {selected.title}", role="success"))

        for candidate in job.topic_candidates:
            layout.addWidget(separator())
            is_selected = job.selected_topic_candidate is candidate
            title_text = candidate.title + (" (selected)" if is_selected else "")
            layout.addWidget(badge(title_text))

            if candidate.overall_score is not None:
                layout.addWidget(
                    small_muted(
                        f"Overall: {candidate.overall_score:.0f} · "
                        f"Audience: {candidate.audience_potential} · "
                        f"Specificity: {candidate.specificity} · "
                        f"Novelty: {candidate.novelty} · "
                        f"Story potential: {candidate.story_potential} · "
                        f"Researchability: {candidate.researchability} · "
                        f"Platform fit: {candidate.platform_fit}"
                    )
                )

            if candidate.ai_recommendation is not None:
                layout.addWidget(small_muted(candidate.ai_recommendation))

            if not is_selected:
                select_button = button("Select this topic", variant="ghost")
                select_button.clicked.connect(
                    lambda _checked=False, c=candidate: self._handle_select_topic_candidate(
                        c
                    )
                )
                layout.addWidget(select_button, alignment=_LEFT)

        layout.addWidget(separator())

        generation_row = QHBoxLayout()
        generation_row.setSpacing(8)

        generate_more_button = button(
            "Generate more", variant="primary", icon_name="research"
        )
        generate_more_button.clicked.connect(
            lambda: self._handle_generate_topic_candidates(replace_existing=False)
        )
        generation_row.addWidget(generate_more_button)

        regenerate_button = button("Regenerate all", variant="ghost")
        regenerate_button.clicked.connect(
            lambda: self._handle_generate_topic_candidates(replace_existing=True)
        )
        generation_row.addWidget(regenerate_button)
        generation_row.addStretch()

        layout.addLayout(generation_row)

        custom_topic_input = QLineEdit()
        custom_topic_input.setPlaceholderText("Enter your own topic")

        custom_row = QHBoxLayout()
        custom_row.setSpacing(8)
        custom_row.addWidget(custom_topic_input)

        use_custom_button = button("Use my own topic", variant="ghost")
        use_custom_button.clicked.connect(
            lambda: self._handle_use_custom_topic(custom_topic_input)
        )
        custom_row.addWidget(use_custom_button)

        layout.addLayout(custom_row)

        self._layout.addWidget(frame)

    def _handle_generate_topic_candidates(self, *, replace_existing: bool) -> None:
        job = self._current_job()

        if job is None:
            return

        try:
            candidates = self._topic_candidate_generation_service.generate(
                seed_idea=job.topic,
                genre_id=job.genre_id,
                platform=job.platform,
            )
        except (RuntimeError, ValueError) as error:
            self._record_error(
                job,
                f"Topic candidate generation failed: {error}",
                on_retry=lambda: self._handle_generate_topic_candidates(
                    replace_existing=replace_existing
                ),
            )

            return

        if replace_existing:
            job.topic_candidates = candidates
        else:
            job.topic_candidates = job.topic_candidates + candidates

        self._on_change()

    def _handle_select_topic_candidate(self, candidate: TopicCandidate) -> None:
        job = self._current_job()

        if job is None:
            return

        job.selected_topic_candidate = candidate
        self._on_change()

    def _handle_use_custom_topic(self, text_input: QLineEdit) -> None:
        job = self._current_job()

        if job is None:
            return

        title = text_input.text().strip()

        if not title:
            return

        try:
            candidate = TopicCandidate.custom(title)
        except ValueError as error:
            self._record_error(job, f"Could not use custom topic: {error}")

            return

        job.topic_candidates = job.topic_candidates + [candidate]
        job.selected_topic_candidate = candidate
        self._on_change()

    def _handle_select_story_angle(self, angle: StoryAngle) -> None:
        job = self._current_job()

        if job is None:
            return

        job.selected_story_angle = angle
        self._on_change()

    def _handle_write_custom_angle(
        self,
        *,
        style_select: QComboBox,
        title_input: QLineEdit,
        description_input: QLineEdit,
    ) -> None:
        job = self._current_job()

        if job is None:
            return

        try:
            angle = StoryAngle(
                style=StoryAngleStyle(style_select.currentText()),
                title=title_input.text(),
                description=description_input.text(),
            )
        except ValueError as error:
            self._record_error(job, f"Could not save custom story angle: {error}")

            return

        job.story_angles = job.story_angles + [angle]
        job.selected_story_angle = angle
        self._on_change()

    def _handle_combine_story_angles(self, other_angle: StoryAngle) -> None:
        job = self._current_job()

        if job is None or job.selected_story_angle is None:
            return

        base_angle = job.selected_story_angle

        if other_angle.title == base_angle.title:
            return

        note = (
            f"Combines '{base_angle.title}' ({base_angle.style.value}) with "
            f"'{other_angle.title}' ({other_angle.style.value}): "
            f"{other_angle.description}"
        )
        existing = job.creative_direction

        try:
            job.creative_direction = CreativeDirection(
                selected_angle=base_angle,
                combined_angle_note=note,
                narrative_thesis=(
                    existing.narrative_thesis if existing else base_angle.description
                ),
                constraints=existing.constraints if existing else [],
            )
        except ValueError as error:
            self._record_error(job, f"Could not combine story angles: {error}")

            return

        self._on_change()

    def _handle_save_creative_direction(
        self, *, thesis_input: QLineEdit, constraints_input: QLineEdit
    ) -> None:
        job = self._current_job()

        if job is None or job.selected_story_angle is None:
            return

        constraints = [
            item.strip() for item in constraints_input.text().split(",") if item.strip()
        ]
        existing = job.creative_direction

        try:
            job.creative_direction = CreativeDirection(
                selected_angle=job.selected_story_angle,
                combined_angle_note=(
                    existing.combined_angle_note if existing else None
                ),
                narrative_thesis=thesis_input.text(),
                constraints=constraints,
            )
        except ValueError as error:
            self._record_error(job, f"Could not save creative direction: {error}")

            return

        self._on_change()

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

        button_row = QHBoxLayout()
        button_row.setSpacing(8)

        run_button = button(
            f"Run {stage_label.lower()}", variant="primary", icon_name="research"
        )
        run_button.setEnabled(can_run)
        run_button.clicked.connect(lambda: self._handle_run_ci_stage(stage_key))
        button_row.addWidget(run_button)

        artifact_type, field_name = _CI_STAGE_REVIEW_TARGET[stage_key]
        artifact = getattr(job, field_name, None)
        reviewer_profile_id = job.provider_preferences.reviewer.reviewer_profile_id

        review_button = button("Review", variant="ghost", icon_name="shield")
        review_button.setEnabled(bool(artifact) and reviewer_profile_id is not None)
        review_button.clicked.connect(
            lambda: self._handle_review_ci_stage(
                stage_key=stage_key, artifact_type=artifact_type, field_name=field_name
            )
        )
        button_row.addWidget(review_button)
        button_row.addStretch()

        layout.addLayout(button_row)

        if reviewer_profile_id is None:
            layout.addWidget(
                small_muted(
                    "No Reviewer configured for this project - set one in "
                    "Project Setup to enable Review."
                )
            )

        self._render_review_result(layout, stage_key)

    def _render_review_result(self, layout: QVBoxLayout, stage_key: str) -> None:
        result = self._last_review_by_stage.get(stage_key)

        if result is None:
            return

        layout.addWidget(separator())
        layout.addWidget(small_muted("Reviewer feedback:"))

        for strength in result.strengths:
            layout.addWidget(status_label(f"+ {strength}", role="success"))

        for issue in result.issues:
            role = "error" if issue.severity.value == "blocking" else "warning"
            text = f"[{issue.severity.value}] {issue.description}"

            if issue.recommendation is not None:
                text += f" -> {issue.recommendation}"

            layout.addWidget(status_label(text, role=role))

        if result.suggested_revision_direction is not None:
            layout.addWidget(
                small_muted(
                    f"Suggested revision direction: "
                    f"{result.suggested_revision_direction}"
                )
            )

    def _handle_review_ci_stage(
        self,
        *,
        stage_key: str,
        artifact_type: ArtifactType,
        field_name: str,
    ) -> None:
        job = self._current_job()

        if job is None:
            return

        artifact = getattr(job, field_name, None)

        if not artifact:
            return

        reviewer_profile_id = job.provider_preferences.reviewer.reviewer_profile_id

        if reviewer_profile_id is None:
            return

        content = self._serialize_artifact_for_review(artifact)
        context = (
            f"Topic: {job.topic}\n"
            f"Genre: {job.genre_id}\n"
            f"Target audience: {job.target_audience}"
        )

        try:
            result = self._reviewer_service.review(
                artifact_type=artifact_type,
                content=content,
                context=context,
                reviewer_profile_id=reviewer_profile_id,
            )
        except (RuntimeError, ValueError) as error:
            self._record_error(job, f"Review failed: {error}")

            return

        if result is not None:
            self._last_review_by_stage[stage_key] = result

        self._on_change()

    @staticmethod
    def _serialize_artifact_for_review(artifact: object) -> str:
        if isinstance(artifact, list):
            return "\n\n".join(
                (
                    item.model_dump_json()
                    if hasattr(item, "model_dump_json")
                    else str(item)
                )
                for item in artifact
            )

        if hasattr(artifact, "model_dump_json"):
            return str(artifact.model_dump_json())

        return str(artifact)

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
            self._record_error(
                job,
                f"Could not resolve approval decision: {error}",
                on_retry=lambda: self._handle_resolve_approval(action),
            )

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

        # Content Studio Redesign, Phase 6: Audience Strategy fields.
        # Display-only, matching every other CI stage panel's current
        # convention - none of these panels support inline field
        # editing yet (a pre-existing, repo-wide gap already flagged
        # in Phase 4's own documented deferrals, not specific to this
        # phase).
        strategy_fields = [
            ("Persona", promise.persona),
            ("Viewer intent", promise.viewer_intent),
            ("Viewer promise", promise.viewer_promise),
            ("Tone/treatment", promise.tone_treatment),
            ("Platform strategy", promise.platform_strategy),
            ("Audience pain/desire", promise.audience_pain_or_desire),
            ("Knowledge assumption", promise.knowledge_assumption),
        ]

        for label, value in strategy_fields:
            if value is not None:
                layout.addWidget(small_muted(f"{label}: {value}"))

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

            angle_action_row = QHBoxLayout()
            angle_action_row.setSpacing(6)

            if not is_selected:
                select_button = button("Select", variant="ghost")
                select_button.clicked.connect(
                    lambda _checked=False, a=angle: self._handle_select_story_angle(a)
                )
                angle_action_row.addWidget(select_button)

            if job.selected_story_angle is not None and not is_selected:
                combine_button = button("Combine with selected", variant="ghost")
                combine_button.clicked.connect(
                    lambda _checked=False, a=angle: self._handle_combine_story_angles(a)
                )
                angle_action_row.addWidget(combine_button)

            angle_action_row.addStretch()
            layout.addLayout(angle_action_row)

        layout.addWidget(separator())
        layout.addWidget(small_muted("Write my own angle:"))

        custom_style_select = QComboBox()
        custom_style_select.addItems([style.value for style in StoryAngleStyle])

        custom_title_input = QLineEdit()
        custom_title_input.setPlaceholderText("Angle title")

        custom_description_input = QLineEdit()
        custom_description_input.setPlaceholderText("Angle description")

        custom_form = QFormLayout()
        custom_form.addRow("Style", custom_style_select)
        custom_form.addRow("Title", custom_title_input)
        custom_form.addRow("Description", custom_description_input)
        layout.addLayout(custom_form)

        write_own_button = button("Write my own angle", variant="ghost")
        write_own_button.clicked.connect(
            lambda: self._handle_write_custom_angle(
                style_select=custom_style_select,
                title_input=custom_title_input,
                description_input=custom_description_input,
            )
        )
        layout.addWidget(write_own_button, alignment=_LEFT)

        layout.addWidget(separator())
        self._render_creative_direction_section(layout, job)

        return True

    def _render_creative_direction_section(
        self, layout: QVBoxLayout, job: VideoJob
    ) -> None:
        """
        Content Studio Redesign, Phase 6: Creative Direction is a
        separate artifact from the selected StoryAngle above - see
        CreativeDirection's own docstring for why - versioned/approved
        independently even though it shares this GUI section.
        """

        layout.addWidget(small_muted("Creative direction:"))

        direction = job.creative_direction

        if direction is not None:
            layout.addWidget(status_label("Saved", role="success"))
            layout.addWidget(muted(f"Narrative thesis: {direction.narrative_thesis}"))

            if direction.combined_angle_note is not None:
                layout.addWidget(
                    small_muted(f"Combined: {direction.combined_angle_note}")
                )

            if direction.constraints:
                layout.addWidget(
                    small_muted("Constraints: " + ", ".join(direction.constraints))
                )

        if job.selected_story_angle is None:
            layout.addWidget(
                small_muted("Select or write an angle above to set a narrative thesis.")
            )

            return

        thesis_input = QLineEdit(direction.narrative_thesis if direction else "")
        thesis_input.setPlaceholderText("Narrative thesis")

        constraints_input = QLineEdit(
            ", ".join(direction.constraints) if direction else ""
        )
        constraints_input.setPlaceholderText("Constraints, comma-separated")

        thesis_form = QFormLayout()
        thesis_form.addRow("Narrative thesis", thesis_input)
        thesis_form.addRow("Constraints", constraints_input)
        layout.addLayout(thesis_form)

        save_button = button("Save creative direction", variant="primary")
        save_button.clicked.connect(
            lambda: self._handle_save_creative_direction(
                thesis_input=thesis_input, constraints_input=constraints_input
            )
        )
        layout.addWidget(save_button, alignment=_LEFT)

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
            self._record_error(
                job,
                f"Content Intelligence stage failed: {error}",
                on_retry=lambda: self._handle_run_ci_stage(stage_key),
            )

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
            self._record_error(
                job,
                f"Could not update script version lock: {error}",
                on_retry=self._handle_toggle_script_version_lock,
            )

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
            self._record_error(
                job,
                f"Research generation failed: {error}",
                on_retry=self._handle_run_research,
            )

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
            self._record_error(
                job,
                f"Script generation failed: {error}",
                on_retry=self._handle_run_script,
            )

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
            self._record_error(
                job,
                f"Originality review failed: {error}",
                on_retry=self._handle_run_originality,
            )

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
            self._record_error(
                job,
                f"Could not save project settings: {error}",
                on_retry=lambda: self._handle_save_settings(
                    genre_select=genre_select,
                    platform_select=platform_select,
                    production_mode_select=production_mode_select,
                    approval_mode_select=approval_mode_select,
                    language_input=language_input,
                    target_country_input=target_country_input,
                ),
            )

            return

        self._on_change()

    def _handle_plan_scenes(self) -> None:
        job = self._current_job()

        if job is None or job.script is None:
            return

        try:
            scenes = self._content_pipeline.scene_planner.plan(job.script)
        except (RuntimeError, ValueError) as error:
            self._record_error(
                job,
                f"Scene planning failed: {error}",
                on_retry=self._handle_plan_scenes,
            )

            return

        job.scenes = scenes
        job.current_stage = WorkflowStage.QUALITY_CHECK
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
