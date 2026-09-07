from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QTextEdit,
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
from src.models.content_decision_record import ContentDecisionRecord, DecisionCategory
from src.models.creative_direction import CreativeDirection
from src.models.enums import Platform, ProductionMode, WorkflowStage
from src.models.hook import HookCandidate, HookEvaluation
from src.models.production_handoff import ProductionHandoffState
from src.models.research import ResearchResult, ResearchSource, SourceStatus
from src.models.research_evidence import (
    EvidenceRecord,
    EvidenceSupportType,
    ManualResearchEdit,
    ResearchFact,
)
from src.models.research_plan import ResearchQuestion
from src.models.reviewer_result import ReviewerResult
from src.models.script_intake import ScriptIntakeMode
from src.models.script_selection_edit import (
    SelectionEditOperation,
    SelectionEditRequest,
)
from src.models.script_version import ScriptVersionComparison
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
from src.services.fact_check_service import FactCheckService
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
    ("writing_directives", "Directives"),
    ("script", "Script"),
    ("continuity_bible", "Continuity bible"),
    ("editorial_critique", "Editorial critique"),
    ("quality_gate", "Quality gate"),
    ("revision", "Revision"),
    ("packaging_hypothesis", "Packaging hypothesis"),
    ("scene_planning", "Scene planning"),
    ("production_readiness", "Production readiness"),
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
    "writing_directives": (ArtifactType.DIRECTIVES, "writing_directives"),
    "script": (ArtifactType.SCRIPT, "generated_script"),
    "continuity_bible": (ArtifactType.STORY_ARCHITECTURE, "continuity_bible"),
    "editorial_critique": (ArtifactType.SCRIPT, "editorial_critique"),
    "quality_gate": (ArtifactType.QUALITY_GATE, "script_quality_report"),
    "revision": (ArtifactType.SCRIPT, "generated_script"),
    "packaging_hypothesis": (ArtifactType.SCRIPT, "packaging_hypothesis"),
    "scene_planning": (ArtifactType.SCRIPT, "scenes"),
    "production_readiness": (ArtifactType.SCRIPT, "generated_script"),
}

# Content Studio Redesign, Phase 12: the fixed selection-edit action
# buttons every segment editor gets. CUSTOM is deliberately excluded -
# it has its own instruction-input row rather than a bare button.
_SELECTION_EDIT_OPERATIONS: list[tuple[SelectionEditOperation, str]] = [
    (SelectionEditOperation.REWRITE, "Rewrite"),
    (SelectionEditOperation.SHORTEN, "Shorten"),
    (SelectionEditOperation.EXPAND, "Expand"),
    (SelectionEditOperation.MORE_SUSPENSEFUL, "More suspenseful"),
    (SelectionEditOperation.MORE_NATURAL, "More natural"),
    (SelectionEditOperation.IMPROVE_TRANSITION, "Improve transition"),
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
        reviewer_service: ReviewerService,
        topic_candidate_generation_service: TopicCandidateGenerationService,
        fact_check_service: FactCheckService,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__()

        self._job_store = job_store
        self._content_pipeline = content_pipeline
        self._content_intelligence_pipeline = content_intelligence_pipeline
        self._reviewer_service = reviewer_service
        self._topic_candidate_generation_service = topic_candidate_generation_service
        self._fact_check_service = fact_check_service
        self._journey_service = ContentStudioJourneyService()
        self._on_change = on_change
        self._job_id: UUID | None = None
        self._selected_ci_stage_index = 0
        # Tracked separately from _job_id (which set_job() already
        # updates before refresh() runs) - see refresh()'s own
        # docstring for why this distinction is what makes scroll-
        # position preservation possible.
        self._last_refreshed_job_id: UUID | None = None

        # Transient - a review is a read-only critique, never persisted
        # to VideoJob (the Reviewer never becomes the author). Keyed by
        # stage_key so switching stages doesn't lose a prior result,
        # cleared only when set_job() moves to a different project.
        self._last_review_by_stage: dict[str, ReviewerResult] = {}

        # Transient - rebuilt fresh every refresh() so a segment's
        # editable text survives redraws only via job.generated_script
        # itself (Save/AI-edit actions persist to the job before the
        # next refresh), matching this view's rebuild-from-job-state
        # convention everywhere else.
        self._script_segment_editors: dict[int, QTextEdit] = {}
        self._script_compare_from: QComboBox | None = None
        self._script_compare_to: QComboBox | None = None
        self._last_script_comparison: ScriptVersionComparison | None = None
        self._quality_finding_checkboxes: dict[UUID, QCheckBox] = {}
        self._script_intake_editor: QTextEdit | None = None
        self._script_intake_mode_select: QComboBox | None = None

        # Content Studio Redesign, Phase 18: Activity History filters -
        # plain strings persisted across refresh() (not live QComboBox
        # references), matching how _selected_ci_stage_index already
        # survives a rebuild without holding onto a widget.
        self._activity_history_category_filter: str = "all"
        self._activity_history_stage_filter: str = "all"

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

        # Kept so refresh() can preserve scroll position across a
        # rebuild - every action on this screen (selecting a topic,
        # running a stage, saving an edit) calls refresh(), which tears
        # down and rebuilds every card from scratch; without this the
        # view silently snapped back to the top after every single
        # click, a real, reported usability problem.
        self._scroll_area = scroll_area

    def set_job(self, job_id: UUID) -> None:
        self._job_id = job_id
        self._last_review_by_stage = {}
        self._last_script_comparison = None
        self._activity_history_category_filter = "all"
        self._activity_history_stage_filter = "all"

    def refresh(self, job: VideoJob) -> None:
        """
        Real-world finding: every action on this screen (selecting a
        topic, running a stage, saving an edit) calls this method,
        which tears down and rebuilds every card from scratch - with
        no scroll-position handling, the view silently snapped back to
        the top after every single click, a real, reported usability
        problem. Fixed by capturing the scrollbar's value before the
        rebuild and restoring it after, UNLESS this refresh is for a
        genuinely different job (switching projects correctly starts
        at the top, not wherever the previous project's scroll
        happened to be) - _last_refreshed_job_id, tracked only here,
        is what distinguishes "just switched projects" from "same
        project, something happened" (job.id itself is already updated
        by set_job() before refresh() ever runs, so it can't be used
        for that comparison).
        """

        is_same_job = job.id == self._last_refreshed_job_id
        scroll_value = (
            self._scroll_area.verticalScrollBar().value() if is_same_job else 0
        )
        self._last_refreshed_job_id = job.id

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
        self._build_production_handoff_card(job)
        self._build_activity_history_card(job)
        self._build_legacy_pipeline_notice(job)
        self._build_workflow_card(job)
        self._build_research_card(job)
        self._build_script_card(job)
        self._build_originality_card(job)
        self._build_scenes_card(job)

        # Deferred to the next event-loop tick: right after a rebuild,
        # the old widgets' deleteLater() calls and the new layout's
        # geometry/size-hint recalculation are still pending, so the
        # scrollbar's range may not yet reflect the new content and
        # setValue() here could get silently clamped to the stale
        # (often smaller, pre-rebuild) range.
        QTimer.singleShot(0, lambda: self._restore_scroll_position(scroll_value))

    def _restore_scroll_position(self, value: int) -> None:
        self._scroll_area.verticalScrollBar().setValue(value)

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

    def _handle_add_research_question(self, text_input: QLineEdit) -> None:
        job = self._current_job()

        if job is None or job.research_plan is None:
            return

        text = text_input.text().strip()

        if not text:
            return

        try:
            question = ResearchQuestion(text=text)
        except ValueError as error:
            self._record_error(job, f"Could not add research question: {error}")

            return

        job.research_plan.structured_questions = (
            job.research_plan.structured_questions + [question]
        )
        job.research_plan.research_questions = job.research_plan.research_questions + [
            text
        ]
        self._on_change()

    def _handle_edit_research_question(
        self, question_id: UUID, text_input: QLineEdit
    ) -> None:
        job = self._current_job()

        if job is None or job.research_plan is None:
            return

        new_text = text_input.text().strip()

        if not new_text:
            return

        updated_questions: list[ResearchQuestion] = []

        for question in job.research_plan.structured_questions:
            if question.id != question_id:
                updated_questions.append(question)

                continue

            try:
                updated_questions.append(
                    ResearchQuestion(id=question.id, text=new_text)
                )
            except ValueError as error:
                self._record_error(job, f"Could not edit research question: {error}")

                return

        job.research_plan.structured_questions = updated_questions
        job.research_plan.research_questions = [q.text for q in updated_questions]
        self._on_change()

    def _handle_remove_research_question(self, question_id: UUID) -> None:
        job = self._current_job()

        if job is None or job.research_plan is None:
            return

        remaining = [
            question
            for question in job.research_plan.structured_questions
            if question.id != question_id
        ]

        if not remaining:
            self._record_error(job, "A research brief requires at least one question.")

            return

        job.research_plan.structured_questions = remaining
        job.research_plan.research_questions = [q.text for q in remaining]
        self._on_change()

    def _handle_approve_research_brief(self) -> None:
        job = self._current_job()

        if job is None:
            return

        try:
            self._content_intelligence_pipeline.resolve_approval(
                job, "research_plan", HumanApprovalAction.APPROVE
            )
        except ValueError as error:
            self._record_error(job, f"Could not approve research brief: {error}")

            return

        self._on_change()

    def _handle_add_research_source(
        self, *, title_input: QLineEdit, url_input: QLineEdit
    ) -> None:
        job = self._current_job()

        if job is None or job.research is None:
            return

        title = title_input.text().strip()

        if not title:
            return

        url = url_input.text().strip() or None

        try:
            source = ResearchSource(title=title, url=url)
        except ValueError as error:
            self._record_error(job, f"Could not add research source: {error}")

            return

        job.research.sources = job.research.sources + [source]
        self._on_change()

    def _handle_toggle_source_status(self, source_id: UUID) -> None:
        job = self._current_job()

        if job is None or job.research is None:
            return

        for source in job.research.sources:
            if source.id == source_id:
                source.status = (
                    SourceStatus.REJECTED
                    if source.status == SourceStatus.ACCEPTED
                    else SourceStatus.ACCEPTED
                )

                break

        self._on_change()

    def _handle_add_manual_research_edit(self, text_input: QLineEdit) -> None:
        job = self._current_job()

        if job is None or job.research is None:
            return

        text = text_input.text().strip()

        if not text:
            return

        try:
            edit = ManualResearchEdit(text=text)
        except ValueError as error:
            self._record_error(job, f"Could not add manual research note: {error}")

            return

        job.research.manual_edits = job.research.manual_edits + [edit]
        self._on_change()

    def _handle_fact_check_again(self, edit_id: UUID) -> None:
        job = self._current_job()

        if job is None or job.research is None:
            return

        target = next(
            (edit for edit in job.research.manual_edits if edit.id == edit_id), None
        )

        if target is None:
            return

        try:
            result = self._fact_check_service.check(
                claim_text=target.text, sources=job.research.sources
            )
        except (RuntimeError, ValueError) as error:
            self._record_error(
                job,
                f"Fact check failed: {error}",
                on_retry=lambda: self._handle_fact_check_again(edit_id),
            )

            return

        # Regression fix (found via external audit): is_verified must
        # agree with whether the resulting ResearchFact actually shows
        # as supported (ResearchFact.is_supported checks len(evidence)
        # > 0) - a result.is_supported=True with no parseable
        # matched_source_ids used to mark the note "verified" (green)
        # while the fact it created showed "unsupported" (amber), a
        # visible contradiction from one click. Treat that ambiguous
        # case as not verified, honestly, rather than trusting an
        # is_supported flag the evidence itself doesn't back up.
        has_matched_evidence = bool(result.matched_source_ids)
        is_actually_verified = result.is_supported and has_matched_evidence
        verification_notes = (
            result.reasoning
            if is_actually_verified
            else (
                f"{result.reasoning} (Reviewer marked this supported but "
                "named no specific source - treated as unverified.)"
                if result.is_supported and not has_matched_evidence
                else result.reasoning
            )
        )

        updated_edits: list[ManualResearchEdit] = []

        for edit in job.research.manual_edits:
            if edit.id != edit_id:
                updated_edits.append(edit)

                continue

            updated_edits.append(
                ManualResearchEdit(
                    id=edit.id,
                    text=edit.text,
                    is_verified=is_actually_verified,
                    verification_notes=verification_notes,
                )
            )

        job.research.manual_edits = updated_edits

        if is_actually_verified:
            job.research.structured_facts = job.research.structured_facts + [
                ResearchFact(
                    text=target.text,
                    evidence=[
                        EvidenceRecord(
                            source_id=source_id,
                            confidence=result.confidence,
                            support_type=EvidenceSupportType.DIRECT,
                        )
                        for source_id in result.matched_source_ids
                    ],
                )
            ]

        self._on_change()

    def _handle_add_research_gap(self, text_input: QLineEdit) -> None:
        job = self._current_job()

        if job is None or job.research is None:
            return

        text = text_input.text().strip()

        if not text:
            return

        job.research.research_gaps = job.research.research_gaps + [text]
        self._on_change()

    def _handle_remove_research_gap(self, gap: str) -> None:
        job = self._current_job()

        if job is None or job.research is None:
            return

        job.research.research_gaps = [
            existing for existing in job.research.research_gaps if existing != gap
        ]
        self._on_change()

    def _handle_regenerate_narrative_architecture(
        self, instruction_input: QLineEdit
    ) -> None:
        """
        Content Studio Redesign, Phase 9: a targeted regeneration
        outside the generic _handle_run_ci_stage dispatch, since that
        dispatch has no way to pass stage-specific keyword arguments -
        this is the "AI instruction example: compress slow middle
        section" GUI action.
        """

        job = self._current_job()

        if job is None:
            return

        instructions = instruction_input.text().strip() or None

        try:
            self._content_intelligence_pipeline.run_narrative_architecture(
                job, additional_instructions=instructions
            )
        except (RuntimeError, ValueError) as error:
            self._record_error(
                job,
                f"Narrative architecture regeneration failed: {error}",
                on_retry=lambda: self._handle_regenerate_narrative_architecture(
                    instruction_input
                ),
            )

            return

        self._on_change()

    def _handle_select_hook(self, hook: HookCandidate) -> None:
        job = self._current_job()

        if job is None:
            return

        evaluation = next(
            (e for e in job.hook_evaluations if e.hook_text == hook.text), None
        )

        if evaluation is None:
            return

        job.selected_hook = evaluation
        self._on_change()

    def _handle_write_custom_hook(self, text_input: QLineEdit) -> None:
        job = self._current_job()

        if job is None:
            return

        text = text_input.text().strip()

        if not text:
            return

        try:
            candidate = HookCandidate(text=text)
            evaluation = HookEvaluation.custom(text)
        except ValueError as error:
            self._record_error(job, f"Could not save custom hook: {error}")

            return

        job.hook_candidates = job.hook_candidates + [candidate]
        job.hook_evaluations = job.hook_evaluations + [evaluation]
        job.selected_hook = evaluation
        self._on_change()

    def _handle_generate_more_hooks(self) -> None:
        job = self._current_job()

        if job is None:
            return

        if (
            job.selected_story_angle is None
            or job.audience_promise is None
            or job.research is None
        ):
            return

        pipeline = self._content_intelligence_pipeline
        editorial_profile = job.editorial_profile_snapshot or (
            pipeline.resolve_editorial_profile(job)
        )

        try:
            new_hooks = pipeline.hook_generation_service.generate(
                topic=job.topic,
                story_angle=job.selected_story_angle,
                audience_promise=job.audience_promise,
                research=job.research,
                editorial_profile=editorial_profile,
            )
            combined_hooks = job.hook_candidates + new_hooks
            evaluations = pipeline.hook_evaluation_service.evaluate(
                topic=job.topic,
                hooks=combined_hooks,
                research=job.research,
                editorial_profile=editorial_profile,
            )
        except (RuntimeError, ValueError) as error:
            self._record_error(
                job,
                f"Generating more hooks failed: {error}",
                on_retry=self._handle_generate_more_hooks,
            )

            return

        job.hook_candidates = combined_hooks
        job.hook_evaluations = evaluations
        self._on_change()

    def _handle_rewrite_hooks_with_instructions(
        self, instruction_input: QLineEdit
    ) -> None:
        job = self._current_job()

        if job is None:
            return

        instructions = instruction_input.text().strip() or None

        try:
            self._content_intelligence_pipeline.run_hooks(
                job, additional_instructions=instructions
            )
        except (RuntimeError, ValueError) as error:
            self._record_error(
                job,
                f"Hook rewrite failed: {error}",
                on_retry=lambda: self._handle_rewrite_hooks_with_instructions(
                    instruction_input
                ),
            )

            return

        self._on_change()

    def _handle_add_project_writing_rule(self, text_input: QLineEdit) -> None:
        job = self._current_job()

        if job is None:
            return

        text = text_input.text().strip()

        if not text:
            return

        job.project_writing_rules = job.project_writing_rules + [text]
        self._on_change()

    def _handle_remove_project_writing_rule(self, rule: str) -> None:
        job = self._current_job()

        if job is None:
            return

        job.project_writing_rules = [
            existing for existing in job.project_writing_rules if existing != rule
        ]
        self._on_change()

    def _handle_add_user_writing_directive(self, text_input: QLineEdit) -> None:
        job = self._current_job()

        if job is None:
            return

        text = text_input.text().strip()

        if not text:
            return

        job.user_writing_directives = job.user_writing_directives + [text]
        self._on_change()

    def _handle_remove_user_writing_directive(self, directive_text: str) -> None:
        job = self._current_job()

        if job is None:
            return

        job.user_writing_directives = [
            existing
            for existing in job.user_writing_directives
            if existing != directive_text
        ]
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

        self._render_automation_status(layout, job)

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

    def _render_automation_status(self, layout: QVBoxLayout, job: VideoJob) -> None:
        """
        Content Studio Redesign, Phase 17: "Run/Resume Automation,"
        "Pause reason and next required user action," "Visible current
        operation and completed stages." Fully Automatic, Custom
        Approvals, and Approve Every Major Stage are all just
        ApprovalPolicyConfig configuration consumed by this same
        run_all()/compute_automation_status() pair - one engine, not
        three separate implementations.
        """

        status = self._content_intelligence_pipeline.compute_automation_status(job)

        run_row = QHBoxLayout()
        run_button = button(
            "Resume automation" if status.completed_stages else "Run automation",
            variant="primary",
        )
        run_button.clicked.connect(self._handle_run_automation)
        run_row.addWidget(run_button)
        run_row.addWidget(badge(f"{len(status.completed_stages)} stage(s) completed"))
        layout.addLayout(run_row)

        if status.is_paused:
            layout.addWidget(
                status_label(
                    f"Paused at '{status.pending_stage}' - "
                    f"'{status.pending_decision_point}' needs your decision "
                    f"below. {status.pending_summary or ''}".strip(),
                    role="warning",
                )
            )
        elif status.is_complete:
            layout.addWidget(
                status_label("Automation has completed every stage.", role="success")
            )

        layout.addWidget(separator())

    def _handle_run_automation(self) -> None:
        job = self._current_job()

        if job is None:
            return

        try:
            self._content_intelligence_pipeline.run_all(job)
        except (RuntimeError, ValueError) as error:
            self._record_error(job, f"Automation stopped: {error}")

            return

        self._on_change()

    def _build_production_handoff_card(self, job: VideoJob) -> None:
        """
        Post-Script-Approval Production Plan, Phase 0: "After final
        approval, show 'Script locked for production' rather than a
        separate manual Plan Clips requirement" / "If downstream build
        fails, show Retry Production Handoff without forcing another
        script approval." Only shown once locking is even possible
        (i.e. a script exists) - a brand-new project with nothing
        produced yet has nothing to hand off.
        """

        if job.generated_script is None:
            return

        frame, layout = card("Production handoff", icon_name="clapper")

        status = self._content_intelligence_pipeline.compute_production_handoff_status(
            job
        )

        state_role = {
            ProductionHandoffState.BLOCKED: "warning",
            ProductionHandoffState.LOCKED: None,
            ProductionHandoffState.BUILDING_PACKAGE: "warning",
            ProductionHandoffState.PACKAGE_READY: "success",
        }[status.state]

        state_text = {
            ProductionHandoffState.BLOCKED: status.blocked_reason
            or "Blocked - no script lock exists yet.",
            ProductionHandoffState.LOCKED: (
                "Script locked for production. Scenes have not been " "planned yet."
            ),
            ProductionHandoffState.BUILDING_PACKAGE: (
                "The script changed since scenes were last planned - "
                "the production package needs rebuilding."
            ),
            ProductionHandoffState.PACKAGE_READY: (
                "Production package is ready - scenes are planned and "
                "match the current script lock."
            ),
        }[status.state]

        if state_role is None:
            layout.addWidget(small_muted(state_text))
        else:
            layout.addWidget(status_label(state_text, role=state_role))

        if status.state in (
            ProductionHandoffState.LOCKED,
            ProductionHandoffState.BUILDING_PACKAGE,
        ):
            retry_button = button(
                (
                    "Retry production handoff"
                    if job.scenes
                    else "Build production package"
                ),
                variant="primary",
            )
            retry_button.clicked.connect(
                lambda: self._handle_run_ci_stage("scene_planning")
            )
            layout.addWidget(retry_button, alignment=_LEFT)

        if job.script_lock is not None:
            layout.addWidget(separator())
            self._render_production_semantic_brief_section(layout, job)

        if job.script_lock is not None and job.scenes and job.continuity_bible:
            layout.addWidget(separator())
            self._render_visual_continuity_section(layout, job)

        if job.script_lock is not None and job.visual_continuity_bible is not None:
            layout.addWidget(separator())
            self._render_shot_planning_section(layout, job)

        if job.script_lock is not None and job.cinematic_shot_plan is not None:
            layout.addWidget(separator())
            self._render_cinematic_prompt_section(layout, job)

        if job.scenes:
            layout.addWidget(separator())
            self._render_clip_materialization_section(layout, job)

        self._layout.addWidget(frame)

    def _render_production_semantic_brief_section(
        self, layout: QVBoxLayout, job: VideoJob
    ) -> None:
        """
        Post-Script-Approval Production Plan, Phase 1: "Production
        Directives tab/inspector" - time range, beat, and visual/
        voice/music/SFX/edit/transition intent per segment. Lives
        inside the Production Handoff card rather than a separate one
        (this plan's own wording calls it a "tab/inspector," not a
        standalone screen), gated on a script lock existing since the
        brief's own primary input is the lock, not just the script.
        """

        brief = job.production_semantic_brief

        if brief is None:
            layout.addWidget(small_muted("No production directives generated yet."))
            generate_button = button(
                "Generate production directives", variant="primary"
            )
            generate_button.clicked.connect(
                self._handle_generate_production_semantic_brief
            )
            layout.addWidget(generate_button, alignment=_LEFT)

            return

        is_stale = job.script_lock is not None and (
            brief.script_lock_hash != job.script_lock.script_content_hash
        )

        layout.addWidget(
            badge(f"Production directives · {len(brief.segments)} segment(s)")
        )

        if is_stale:
            layout.addWidget(
                status_label(
                    "Stale - the script was re-locked since these directives "
                    "were generated.",
                    role="warning",
                )
            )

        for segment in brief.segments:
            layout.addWidget(
                small_muted(
                    f"{segment.start_seconds:.0f}s-{segment.end_seconds:.0f}s "
                    f"({segment.beat_type}): {segment.visual_intent} "
                    f"{segment.voice_intent} {segment.music_intent}"
                )
            )

        regenerate_button = button("Regenerate production directives", variant="ghost")
        regenerate_button.clicked.connect(
            self._handle_generate_production_semantic_brief
        )
        layout.addWidget(regenerate_button, alignment=_LEFT)

    def _handle_generate_production_semantic_brief(self) -> None:
        job = self._current_job()

        if job is None:
            return

        try:
            self._content_intelligence_pipeline.run_production_semantic_brief(job)
        except (RuntimeError, ValueError) as error:
            self._record_error(
                job,
                f"Could not generate production directives: {error}",
                on_retry=self._handle_generate_production_semantic_brief,
            )

            return

        self._on_change()

    def _render_visual_continuity_section(
        self, layout: QVBoxLayout, job: VideoJob
    ) -> None:
        """
        Post-Script-Approval Production Plan, Phase 2: "Optional Bible
        view lists identities, canonical descriptions and references"
        / "Highlight state changes and blocked contradictions." Lives
        alongside the Production Directives section in the same
        Production Handoff card - both are read-only inspectors over
        post-lock production artifacts, not separate workflow stages.
        """

        bible = job.visual_continuity_bible

        if bible is None:
            layout.addWidget(small_muted("No visual continuity bible generated yet."))
            generate_button = button(
                "Generate visual continuity bible", variant="primary"
            )
            generate_button.clicked.connect(self._handle_generate_visual_continuity)
            layout.addWidget(generate_button, alignment=_LEFT)

            return

        layout.addWidget(
            badge(
                f"Visual continuity · {len(bible.identities)} identit(ies) · "
                f"{len(bible.clip_entries)} clip entr(ies)"
            )
        )

        validation = (
            self._content_intelligence_pipeline.compute_visual_continuity_validation(
                job
            )
        )

        if validation is not None and not validation.is_consistent:
            layout.addWidget(
                status_label(
                    f"{len(validation.conflicts)} continuity conflict(s) found - "
                    "see below.",
                    role="warning",
                )
            )
            for conflict in validation.conflicts:
                layout.addWidget(
                    small_muted(f"Scene {conflict.scene_number}: {conflict.detail}")
                )
        elif validation is not None:
            layout.addWidget(
                status_label("No continuity conflicts detected.", role="success")
            )

        for identity in bible.identities:
            layout.addWidget(
                small_muted(
                    f"{identity.entity_type.value.title()}: {identity.name} - "
                    f"{identity.canonical_description}"
                )
            )

        regenerate_button = button(
            "Regenerate visual continuity bible", variant="ghost"
        )
        regenerate_button.clicked.connect(self._handle_generate_visual_continuity)
        layout.addWidget(regenerate_button, alignment=_LEFT)

    def _handle_generate_visual_continuity(self) -> None:
        job = self._current_job()

        if job is None:
            return

        try:
            self._content_intelligence_pipeline.run_visual_continuity(job)
        except (RuntimeError, ValueError) as error:
            self._record_error(
                job,
                f"Could not generate visual continuity bible: {error}",
                on_retry=self._handle_generate_visual_continuity,
            )

            return

        self._on_change()

    def _render_shot_planning_section(self, layout: QVBoxLayout, job: VideoJob) -> None:
        """
        Post-Script-Approval Production Plan, Phase 3: "Clip card
        shows clip number/source/duration/shot summary" / "Clip
        inspector shows full shot details plus intra-shot timeline."
        Also lives inside the Production Handoff card alongside
        Production Directives and Visual Continuity - all three are
        read-only inspectors over the same post-lock production
        chain.
        """

        plan = job.cinematic_shot_plan

        if plan is None:
            layout.addWidget(small_muted("No cinematic shot plan generated yet."))
            generate_button = button("Generate cinematic shot plan", variant="primary")
            generate_button.clicked.connect(self._handle_generate_shot_plan)
            layout.addWidget(generate_button, alignment=_LEFT)

            return

        layout.addWidget(badge(f"Cinematic shot plan · {len(plan.shots)} shot(s)"))

        if not plan.has_exactly_one_shot_per_scene:
            layout.addWidget(
                status_label(
                    "Some scenes have more than one shot specification.",
                    role="warning",
                )
            )

        for shot in sorted(plan.shots, key=lambda s: s.scene_number):
            layout.addWidget(
                small_muted(
                    f"Scene {shot.scene_number} ({shot.duration_seconds:.0f}s): "
                    f"{shot.shot_size.value.replace('_', ' ')} · "
                    f"{shot.shot_angle.value.replace('_', ' ')} · "
                    f"{shot.movement.value} - {shot.action}"
                )
            )

        regenerate_button = button("Regenerate cinematic shot plan", variant="ghost")
        regenerate_button.clicked.connect(self._handle_generate_shot_plan)
        layout.addWidget(regenerate_button, alignment=_LEFT)

    def _handle_generate_shot_plan(self) -> None:
        job = self._current_job()

        if job is None:
            return

        try:
            self._content_intelligence_pipeline.run_shot_planning(job)
        except (RuntimeError, ValueError) as error:
            self._record_error(
                job,
                f"Could not generate cinematic shot plan: {error}",
                on_retry=self._handle_generate_shot_plan,
            )

            return

        self._on_change()

    def _render_cinematic_prompt_section(
        self, layout: QVBoxLayout, job: VideoJob
    ) -> None:
        """
        Post-Script-Approval Production Plan, Phase 4: "Clip inspector
        shows the exact final Flow prompt. Expose negatives,
        references, quality scores and prompt version in collapsible
        sections. Copy Prompt remains a recovery aid, not the primary
        route." No dedicated "Copy Prompt" button is added here - this
        panel already reads directly from the persisted, validated
        prompt package, which is what makes copying unnecessary as
        the primary route in the first place.
        """

        package = job.cinematic_prompt_package

        if package is None:
            layout.addWidget(small_muted("No cinematic prompt package compiled yet."))
            compile_button = button("Compile cinematic prompts", variant="primary")
            compile_button.clicked.connect(self._handle_compile_cinematic_prompts)
            layout.addWidget(compile_button, alignment=_LEFT)

            return

        layout.addWidget(
            badge(f"Cinematic prompt package · {len(package.prompts)} prompt(s)")
        )

        if package.is_ready:
            layout.addWidget(
                status_label("Every prompt is scored and ready.", role="success")
            )
        elif package.blocked_prompts:
            layout.addWidget(
                status_label(
                    f"{len(package.blocked_prompts)} prompt(s) blocked - "
                    "below the quality floor.",
                    role="warning",
                )
            )
        else:
            layout.addWidget(small_muted("Not yet scored."))

        for prompt in sorted(package.prompts, key=lambda p: p.scene_number):
            score_text = (
                f"lowest score {prompt.lowest_score}"
                if prompt.is_scored
                else "unscored"
            )
            layout.addWidget(
                small_muted(
                    f"Scene {prompt.scene_number} (v{prompt.prompt_version}, "
                    f"{score_text}): {prompt.prompt_text}"
                )
            )
            if prompt.negative_constraints:
                layout.addWidget(
                    small_muted("Negative: " + "; ".join(prompt.negative_constraints))
                )

        button_row = QHBoxLayout()
        button_row.setSpacing(6)

        recompile_button = button("Recompile prompts", variant="ghost")
        recompile_button.clicked.connect(self._handle_compile_cinematic_prompts)
        button_row.addWidget(recompile_button)

        score_button = button("Score prompt quality", variant="primary")
        score_button.clicked.connect(self._handle_score_cinematic_prompts)
        button_row.addWidget(score_button)

        button_row.addStretch()
        layout.addLayout(button_row)

    def _handle_compile_cinematic_prompts(self) -> None:
        job = self._current_job()

        if job is None:
            return

        try:
            self._content_intelligence_pipeline.run_cinematic_prompt_compilation(job)
        except (RuntimeError, ValueError) as error:
            self._record_error(
                job,
                f"Could not compile cinematic prompts: {error}",
                on_retry=self._handle_compile_cinematic_prompts,
            )

            return

        self._on_change()

    def _handle_score_cinematic_prompts(self) -> None:
        job = self._current_job()

        if job is None:
            return

        try:
            self._content_intelligence_pipeline.run_cinematic_prompt_quality(job)
        except (RuntimeError, ValueError) as error:
            self._record_error(
                job,
                f"Could not score cinematic prompt quality: {error}",
                on_retry=self._handle_score_cinematic_prompts,
            )

            return

        self._on_change()

    def _render_clip_materialization_section(
        self, layout: QVBoxLayout, job: VideoJob
    ) -> None:
        """
        Post-Script-Approval Production Plan, Phase 5: "Top summary
        includes total/ready/missing, route counts, duration
        integrity and estimated generation budget." Purely a read-only
        summary - Scene itself is already this codebase's real Clip
        Workspace (see Clip Workspace's own view for the per-clip
        detail/fulfillment actions); nothing here duplicates that.
        """

        status = (
            self._content_intelligence_pipeline.compute_clip_materialization_status(job)
        )

        layout.addWidget(
            badge(
                f"Clips · {status.ready_clips}/{status.total_clips} ready, "
                f"{status.missing_clips} missing"
            )
        )

        if status.stale_clips:
            layout.addWidget(
                status_label(
                    f"{status.stale_clips} clip(s) stale against the current "
                    "script lock.",
                    role="warning",
                )
            )

        route_summary = ", ".join(
            f"{route.replace('_', ' ')}: {count}"
            for route, count in sorted(status.route_counts.items())
        )
        layout.addWidget(small_muted(f"Routes: {route_summary or 'none'}"))

        delta = status.duration_delta_seconds
        delta_text = (
            f"+{delta:.0f}s over target"
            if delta > 0
            else (f"{delta:.0f}s under target" if delta < 0 else "matches target")
        )
        layout.addWidget(
            small_muted(
                f"Duration: {status.planned_duration_seconds:.0f}s planned "
                f"({delta_text})."
            )
        )
        if status.has_budget_cap:
            budget_text = (
                f"Estimated cost: ${status.total_estimated_cost:.2f} of "
                f"${status.maximum_visual_budget:.2f} budget "
                f"(${status.remaining_budget:.2f} remaining)."
            )
            if status.is_over_budget:
                layout.addWidget(status_label(budget_text, role="warning"))
            else:
                layout.addWidget(small_muted(budget_text))
        else:
            layout.addWidget(
                small_muted(
                    f"Estimated cost: ${status.total_estimated_cost:.2f} "
                    "(no budget cap configured)."
                )
            )

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
            "writing_directives": self._render_writing_directives_panel,
            "script": self._render_ci_script_panel,
            "continuity_bible": self._render_continuity_bible_panel,
            "editorial_critique": self._render_editorial_critique_panel,
            "quality_gate": self._render_quality_gate_panel,
            "revision": self._render_revision_panel,
            "packaging_hypothesis": self._render_packaging_hypothesis_panel,
            "scene_planning": self._render_scene_planning_panel,
            "production_readiness": self._render_production_readiness_panel,
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
        artifact = self._resolve_review_artifact(job, stage_key, field_name)
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

        artifact = self._resolve_review_artifact(job, stage_key, field_name)

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
    def _resolve_review_artifact(
        job: VideoJob, stage_key: str, field_name: str
    ) -> object | None:
        """
        Return what the Reviewer should actually see for one stage.

        Fixes an undisclosed Phase 6 gap (found via external audit):
        _CI_STAGE_REVIEW_TARGET maps "story_angles" to the field
        "selected_story_angle" so the generic per-stage wiring has one
        artifact to fetch, but Phase 6 added CreativeDirection
        (narrative thesis, constraints, combined-angle note) as a
        richer wrapper around that same selected angle - reviewing only
        the bare StoryAngle meant the Reviewer never saw any of it.
        When creative_direction exists, review that instead - it
        already embeds the selected angle via its own selected_angle
        field, so nothing is lost, only added.
        """

        if stage_key == "story_angles" and job.creative_direction is not None:
            return job.creative_direction

        return getattr(job, field_name, None)

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

    def _build_activity_history_card(self, job: VideoJob) -> None:
        """
        Content Studio Redesign, Phase 18: "Project Activity/History
        panel" - a single chronological, filterable timeline over
        every ContentDecisionRecord, not only approval-gated ones.

        Reuses job.content_decisions as the sole ledger (the same one
        ApprovalGateService.gate()/resolve() already wrote to before
        this phase) rather than introducing a second history model;
        this phase's actual new work was widening which stages write
        to it (see ApprovalGateService.record_event and the pipeline's
        new record_event() calls) and this filtered timeline view.
        """

        frame, layout = card("Activity history", icon_name="shield")

        if not job.content_decisions:
            layout.addWidget(small_muted("No activity recorded yet."))
            self._layout.addWidget(frame)

            return

        filter_row = QHBoxLayout()
        filter_row.setSpacing(6)

        category_select = QComboBox()
        category_select.addItem("All categories", "all")
        for category in DecisionCategory:
            category_select.addItem(
                category.value.replace("_", " ").title(), category.value
            )
        category_select.setCurrentIndex(
            category_select.findData(self._activity_history_category_filter)
        )
        category_select.currentIndexChanged.connect(
            lambda: self._handle_activity_history_category_filter_changed(
                category_select.currentData()
            )
        )
        filter_row.addWidget(category_select)

        stages_present = sorted({record.stage for record in job.content_decisions})
        stage_select = QComboBox()
        stage_select.addItem("All stages", "all")
        for stage in stages_present:
            stage_select.addItem(stage.replace("_", " ").title(), stage)
        stage_index = stage_select.findData(self._activity_history_stage_filter)
        stage_select.setCurrentIndex(stage_index if stage_index >= 0 else 0)
        stage_select.currentIndexChanged.connect(
            lambda: self._handle_activity_history_stage_filter_changed(
                stage_select.currentData()
            )
        )
        filter_row.addWidget(stage_select)
        filter_row.addStretch()
        layout.addLayout(filter_row)

        visible_records = [
            record
            for record in reversed(job.content_decisions)
            if (
                self._activity_history_category_filter == "all"
                or record.effective_category.value
                == self._activity_history_category_filter
            )
            and (
                self._activity_history_stage_filter == "all"
                or record.stage == self._activity_history_stage_filter
            )
        ]

        if not visible_records:
            layout.addWidget(small_muted("No activity matches the current filters."))

        for record in visible_records:
            self._render_activity_history_entry(layout, record)

        pending = ApprovalGateService.latest_pending(job)

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

    @staticmethod
    def _render_activity_history_entry(
        layout: QVBoxLayout, record: ContentDecisionRecord
    ) -> None:
        approval = record.approval
        category_label = record.effective_category.value.replace("_", " ")
        state_text = approval.state.value if approval is not None else category_label

        timestamp = record.created_at.strftime("%Y-%m-%d %H:%M")
        layout.addWidget(badge(f"{record.stage} · {state_text} · {timestamp}"))
        layout.addWidget(small_muted(record.summary))

        if approval is not None and approval.confidence is not None:
            layout.addWidget(small_muted(f"Confidence: {approval.confidence:.2f}"))

    def _handle_activity_history_category_filter_changed(self, category: str) -> None:
        if not category:
            return

        self._activity_history_category_filter = category
        job = self._current_job()

        if job is not None:
            self.refresh(job)

    def _handle_activity_history_stage_filter_changed(self, stage: str) -> None:
        if not stage:
            return

        self._activity_history_stage_filter = stage
        job = self._current_job()

        if job is not None:
            self.refresh(job)

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
        """
        Content Studio Redesign, Phase 7 (Research Center): the
        Research Brief tab. Editable per-question Add/Edit/Remove
        (stable IDs via ResearchQuestion) and an explicit "Approve
        Brief & Start Research" action once the brief's approval
        policy requires one - see ApprovalPolicyConfig.research_plan.
        """

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

        # Lazily backfill stable-ID questions for a plan saved before
        # this phase existed - text stays identical, only
        # structured_questions goes from empty to populated.
        if not plan.structured_questions and plan.research_questions:
            plan.structured_questions = [
                ResearchQuestion(text=text) for text in plan.research_questions
            ]

        is_pending = ApprovalGateService.is_blocked(job, "research_plan")
        layout.addWidget(
            status_label(
                "Pending brief approval" if is_pending else "Brief approved",
                role="warning" if is_pending else "success",
            )
        )

        for question in plan.structured_questions:
            question_row = QHBoxLayout()
            question_row.setSpacing(6)

            question_input = QLineEdit(question.text)
            question_row.addWidget(question_input)

            save_button = button("Save", variant="ghost")
            save_button.clicked.connect(
                lambda _checked=False, qid=question.id, inp=question_input: (
                    self._handle_edit_research_question(qid, inp)
                )
            )
            question_row.addWidget(save_button)

            remove_button = button("Remove", variant="ghost")
            remove_button.clicked.connect(
                lambda _checked=False, qid=question.id: (
                    self._handle_remove_research_question(qid)
                )
            )
            question_row.addWidget(remove_button)

            layout.addLayout(question_row)

        layout.addWidget(separator())

        new_question_input = QLineEdit()
        new_question_input.setPlaceholderText("New research question")

        add_row = QHBoxLayout()
        add_row.setSpacing(6)
        add_row.addWidget(new_question_input)

        add_button = button("Add question", variant="ghost")
        add_button.clicked.connect(
            lambda: self._handle_add_research_question(new_question_input)
        )
        add_row.addWidget(add_button)
        layout.addLayout(add_row)

        if is_pending:
            layout.addWidget(separator())

            approve_button = button(
                "Approve Brief & Start Research", variant="primary", icon_name="check"
            )
            approve_button.clicked.connect(self._handle_approve_research_brief)
            layout.addWidget(approve_button, alignment=_LEFT)

        return True

    def _render_ci_research_panel(self, layout: QVBoxLayout, job: VideoJob) -> bool:
        research = job.research

        # Content Studio Redesign, Phase 7: "No retrieval job starts
        # until brief approval/start action" - blocks the Run button
        # (not just a soft warning) while the brief's approval is
        # still pending.
        if job.research_plan is not None and ApprovalGateService.is_blocked(
            job, "research_plan"
        ):
            layout.addWidget(small_muted("Waiting on Research Brief approval."))

            return False

        if research is None:
            layout.addWidget(small_muted("Not started."))

            return True

        layout.addWidget(badge(research.status.value))
        layout.addWidget(muted(research.research_summary))

        self._render_evidence_ledger_section(layout, job, research)

        return True

    def _render_evidence_ledger_section(
        self, layout: QVBoxLayout, job: VideoJob, research: ResearchResult
    ) -> None:
        """
        Content Studio Redesign, Phase 8 (Research Execution, Evidence
        Ledger and Fact Integrity): sources with accept/reject status,
        evidence-bound facts, manual research edits with fact-check-
        again, and research gaps - all as sections within the existing
        "Research" panel rather than separate tabs (see this phase's
        own honest-scoping note on why the multi-tab shell is deferred
        to Phase 8's own docs entry).
        """

        layout.addWidget(separator())
        layout.addWidget(small_muted("Sources:"))

        for source in research.sources:
            source_row = QHBoxLayout()
            source_row.setSpacing(6)

            label = source.title + (
                f" ({source.publisher})" if source.publisher else ""
            )
            role = "success" if source.status == SourceStatus.ACCEPTED else "warning"
            source_row.addWidget(
                status_label(f"{label} · {source.status.value}", role=role)
            )
            source_row.addStretch()

            toggle_button = button(
                "Reject" if source.status == SourceStatus.ACCEPTED else "Restore",
                variant="ghost",
            )
            toggle_button.clicked.connect(
                lambda _checked=False, sid=source.id: self._handle_toggle_source_status(
                    sid
                )
            )
            source_row.addWidget(toggle_button)

            layout.addLayout(source_row)

        source_title_input = QLineEdit()
        source_title_input.setPlaceholderText("Source title")
        source_url_input = QLineEdit()
        source_url_input.setPlaceholderText("Source URL (optional)")

        add_source_row = QHBoxLayout()
        add_source_row.setSpacing(6)
        add_source_row.addWidget(source_title_input)
        add_source_row.addWidget(source_url_input)

        add_source_button = button("Add source", variant="ghost")
        add_source_button.clicked.connect(
            lambda: self._handle_add_research_source(
                title_input=source_title_input, url_input=source_url_input
            )
        )
        add_source_row.addWidget(add_source_button)
        layout.addLayout(add_source_row)

        if research.structured_facts:
            layout.addWidget(separator())
            layout.addWidget(small_muted("Key facts (evidence-bound):"))

            for fact in research.structured_facts:
                role = "success" if fact.is_supported else "warning"
                layout.addWidget(status_label(fact.text, role=role))

                for record in fact.evidence:
                    layout.addWidget(
                        small_muted(
                            f"  - {record.support_type.value} · "
                            f"confidence {record.confidence} · "
                            f"{record.contradiction_status.value}"
                        )
                    )

        layout.addWidget(separator())
        layout.addWidget(small_muted("Manual research notes:"))

        for edit in research.manual_edits:
            edit_row_text = (
                f"{edit.text} · {'verified' if edit.is_verified else 'unverified'}"
            )
            layout.addWidget(
                status_label(
                    edit_row_text, role="success" if edit.is_verified else "warning"
                )
            )

            if edit.verification_notes is not None:
                layout.addWidget(small_muted(edit.verification_notes))

            if not edit.is_verified:
                fact_check_button = button("Fact Check Again", variant="ghost")
                fact_check_button.clicked.connect(
                    lambda _checked=False, eid=edit.id: self._handle_fact_check_again(
                        eid
                    )
                )
                layout.addWidget(fact_check_button, alignment=_LEFT)

        manual_edit_input = QLineEdit()
        manual_edit_input.setPlaceholderText("Add a manual research note")

        add_edit_row = QHBoxLayout()
        add_edit_row.setSpacing(6)
        add_edit_row.addWidget(manual_edit_input)

        add_edit_button = button("Add note", variant="ghost")
        add_edit_button.clicked.connect(
            lambda: self._handle_add_manual_research_edit(manual_edit_input)
        )
        add_edit_row.addWidget(add_edit_button)
        layout.addLayout(add_edit_row)

        layout.addWidget(separator())
        layout.addWidget(small_muted("Research gaps:"))

        for gap in research.research_gaps:
            gap_row = QHBoxLayout()
            gap_row.setSpacing(6)
            gap_row.addWidget(small_muted(f"- {gap}"))
            gap_row.addStretch()

            remove_gap_button = button("Remove", variant="ghost")
            remove_gap_button.clicked.connect(
                lambda _checked=False, g=gap: self._handle_remove_research_gap(g)
            )
            gap_row.addWidget(remove_gap_button)
            layout.addLayout(gap_row)

        gap_input = QLineEdit()
        gap_input.setPlaceholderText("Add a research gap")

        add_gap_row = QHBoxLayout()
        add_gap_row.setSpacing(6)
        add_gap_row.addWidget(gap_input)

        add_gap_button = button("Add gap", variant="ghost")
        add_gap_button.clicked.connect(lambda: self._handle_add_research_gap(gap_input))
        add_gap_row.addWidget(add_gap_button)
        layout.addLayout(add_gap_row)

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

            beat_detail_parts = []

            if beat.evidence_fact_ids:
                beat_detail_parts.append(f"{len(beat.evidence_fact_ids)} fact(s) cited")

            if beat.curiosity_loop_question is not None:
                beat_detail_parts.append(f"advances: {beat.curiosity_loop_question}")

            if beat_detail_parts:
                layout.addWidget(small_muted("  " + " · ".join(beat_detail_parts)))

        if job.reveal_map is not None:
            layout.addWidget(
                small_muted(
                    f"{len(job.reveal_map.curiosity_loops)} curiosity loop(s), "
                    f"{len(job.reveal_map.reveals)} reveal(s) planned."
                )
            )

        if job.story_blueprint.research_id is not None:
            layout.addWidget(
                small_muted(f"Grounded in research {job.story_blueprint.research_id}")
            )

        layout.addWidget(separator())

        instruction_input = QLineEdit()
        instruction_input.setPlaceholderText(
            "AI instruction, e.g. 'compress the slow middle section'"
        )

        instruction_row = QHBoxLayout()
        instruction_row.setSpacing(6)
        instruction_row.addWidget(instruction_input)

        regenerate_button = button("Regenerate with instructions", variant="ghost")
        regenerate_button.clicked.connect(
            lambda: self._handle_regenerate_narrative_architecture(instruction_input)
        )
        instruction_row.addWidget(regenerate_button)
        layout.addLayout(instruction_row)

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

            detail_parts = []

            if hook.type is not None:
                detail_parts.append(f"type: {hook.type.value}")

            if hook.fact_ids:
                detail_parts.append(f"{len(hook.fact_ids)} fact(s) cited")

            if evaluation is not None:
                detail_parts.append(f"reveal risk: {evaluation.spoiler_risk}")

            if detail_parts:
                layout.addWidget(small_muted("  " + " · ".join(detail_parts)))

            if not is_selected:
                select_button = button("Select", variant="ghost")
                select_button.clicked.connect(
                    lambda _checked=False, h=hook: self._handle_select_hook(h)
                )
                layout.addWidget(select_button, alignment=_LEFT)

        if job.re_hook_plan is not None:
            for re_hook in job.re_hook_plan.re_hooks:
                layout.addWidget(
                    small_muted(
                        f"Re-hook @ {re_hook.position_seconds:.0f}s "
                        f"[{re_hook.re_hook_type.value}]: {re_hook.text}"
                    )
                )

        layout.addWidget(separator())
        layout.addWidget(small_muted("Write my own hook:"))

        custom_hook_input = QLineEdit()
        custom_hook_input.setPlaceholderText("Hook text")

        custom_row = QHBoxLayout()
        custom_row.setSpacing(6)
        custom_row.addWidget(custom_hook_input)

        write_own_button = button("Write my own hook", variant="ghost")
        write_own_button.clicked.connect(
            lambda: self._handle_write_custom_hook(custom_hook_input)
        )
        custom_row.addWidget(write_own_button)
        layout.addLayout(custom_row)

        layout.addWidget(separator())

        instruction_input = QLineEdit()
        instruction_input.setPlaceholderText(
            "AI instruction, e.g. 'make it more suspenseful'"
        )

        instruction_row = QHBoxLayout()
        instruction_row.setSpacing(6)
        instruction_row.addWidget(instruction_input)

        generate_more_button = button("Generate more", variant="ghost")
        generate_more_button.clicked.connect(lambda: self._handle_generate_more_hooks())
        instruction_row.addWidget(generate_more_button)

        rewrite_button = button("Rewrite with instructions", variant="ghost")
        rewrite_button.clicked.connect(
            lambda: self._handle_rewrite_hooks_with_instructions(instruction_input)
        )
        instruction_row.addWidget(rewrite_button)
        layout.addLayout(instruction_row)

        return True

    def _render_writing_directives_panel(
        self, layout: QVBoxLayout, job: VideoJob
    ) -> bool:
        """
        Content Studio Redesign, Phase 11: Script Workspace - Writing
        Directives. Deliberately kept distinct from Story Architecture
        - this panel never touches job.story_blueprint/.reveal_map.
        """

        if job.writing_directives is None:
            can_run = job.selected_hook is not None
            layout.addWidget(
                small_muted(
                    "Not started." if can_run else "Requires a selected hook first."
                )
            )
            self._render_writing_directive_inputs(layout, job)

            return can_run

        for directive in job.writing_directives.directives:
            lock_note = "" if directive.overridable else " · non-overridable"
            layout.addWidget(badge(f"{directive.source.value}{lock_note}"))
            layout.addWidget(small_muted(directive.text))

        layout.addWidget(separator())
        self._render_writing_directive_inputs(layout, job)

        return True

    def _render_writing_directive_inputs(
        self, layout: QVBoxLayout, job: VideoJob
    ) -> None:
        layout.addWidget(small_muted("Project rules:"))

        for rule in job.project_writing_rules:
            rule_row = QHBoxLayout()
            rule_row.setSpacing(6)
            rule_row.addWidget(small_muted(f"- {rule}"))

            remove_rule_button = button("Remove", variant="ghost")
            remove_rule_button.clicked.connect(
                lambda _checked=False, r=rule: self._handle_remove_project_writing_rule(
                    r
                )
            )
            rule_row.addWidget(remove_rule_button)
            layout.addLayout(rule_row)

        new_rule_input = QLineEdit()
        new_rule_input.setPlaceholderText("New project rule")

        rule_add_row = QHBoxLayout()
        rule_add_row.setSpacing(6)
        rule_add_row.addWidget(new_rule_input)

        add_rule_button = button("Add project rule", variant="ghost")
        add_rule_button.clicked.connect(
            lambda: self._handle_add_project_writing_rule(new_rule_input)
        )
        rule_add_row.addWidget(add_rule_button)
        layout.addLayout(rule_add_row)

        layout.addWidget(small_muted("Your directives:"))

        for directive_text in job.user_writing_directives:
            directive_row = QHBoxLayout()
            directive_row.setSpacing(6)
            directive_row.addWidget(small_muted(f"- {directive_text}"))

            remove_directive_button = button("Remove", variant="ghost")
            remove_directive_button.clicked.connect(
                lambda _checked=False, d=directive_text: (
                    self._handle_remove_user_writing_directive(d)
                )
            )
            directive_row.addWidget(remove_directive_button)
            layout.addLayout(directive_row)

        new_directive_input = QLineEdit()
        new_directive_input.setPlaceholderText(
            "New directive, e.g. 'avoid rhetorical questions'"
        )

        directive_add_row = QHBoxLayout()
        directive_add_row.setSpacing(6)
        directive_add_row.addWidget(new_directive_input)

        add_directive_button = button("Add directive", variant="ghost")
        add_directive_button.clicked.connect(
            lambda: self._handle_add_user_writing_directive(new_directive_input)
        )
        directive_add_row.addWidget(add_directive_button)
        layout.addLayout(directive_add_row)

    def _render_ci_script_panel(self, layout: QVBoxLayout, job: VideoJob) -> bool:
        """
        Content Studio Redesign, Phase 12: a real editable Script
        Editor, not a static read-only card. Each segment gets its own
        editable text box plus a row of selection-scoped AI edit
        actions (Rewrite/Shorten/Expand/More Suspenseful/More
        Natural/Improve Transition/Custom Instruction) - an action
        applies to whatever text is currently selected in that
        segment's box, or the whole segment when nothing is selected.
        A separate "Save typed edit" button records a person's own
        direct rewrite as its own manual-edit version, with no AI call
        at all.
        """

        script = job.generated_script

        if script is None:
            can_run = job.selected_hook is not None
            layout.addWidget(
                small_muted(
                    "Not started." if can_run else "Requires a selected hook first."
                )
            )

            self._render_script_intake_section(layout, job)

            return can_run

        layout.addWidget(
            badge(f"{len(script.segments)} segments · {script.word_count} words")
        )

        if job.script_intake_result is not None:
            self._render_script_intake_summary(layout, job)

        history = job.script_version_history
        locked = history is not None and history.is_locked

        if locked:
            layout.addWidget(
                small_muted(
                    "The current version is locked - unlock it in Versions "
                    "below before editing."
                )
            )

        self._script_segment_editors = {}
        ordered_segments = sorted(
            script.segments, key=lambda segment: segment.segment_number
        )

        for segment in ordered_segments:
            layout.addWidget(
                small_muted(
                    f"Segment {segment.segment_number} "
                    f"[{segment.narrative_function.value}, "
                    f"{segment.start_seconds:.0f}s-{segment.end_seconds:.0f}s]"
                )
            )

            editor = QTextEdit()
            editor.setPlainText(segment.narration)
            editor.setReadOnly(locked)
            editor.setFixedHeight(90)
            self._script_segment_editors[segment.segment_number] = editor
            layout.addWidget(editor)

            if not locked:
                actions_row = QHBoxLayout()

                for operation, label in _SELECTION_EDIT_OPERATIONS:
                    action_button = button(label, variant="ghost")
                    action_button.clicked.connect(
                        lambda _checked=False, seg=segment.segment_number, op=operation: (
                            self._handle_script_selection_edit(seg, op)
                        )
                    )
                    actions_row.addWidget(action_button)

                layout.addLayout(actions_row)

                custom_row = QHBoxLayout()
                custom_input = QLineEdit()
                custom_input.setPlaceholderText("Custom instruction...")
                custom_row.addWidget(custom_input)
                custom_button = button("Apply custom edit", variant="ghost")
                custom_button.clicked.connect(
                    lambda _checked=False, seg=segment.segment_number, inp=custom_input: (
                        self._handle_script_custom_selection_edit(seg, inp)
                    )
                )
                custom_row.addWidget(custom_button)
                layout.addLayout(custom_row)

                save_button = button("Save typed edit", variant="ghost")
                save_button.clicked.connect(
                    lambda _checked=False, seg=segment.segment_number: (
                        self._handle_save_script_segment_edit(seg)
                    )
                )
                layout.addWidget(save_button, alignment=_LEFT)

            layout.addWidget(separator())

        self._render_script_version_history(layout, job)

        return True

    def _render_script_intake_section(self, layout: QVBoxLayout, job: VideoJob) -> None:
        """
        Content Studio Redesign, Phase 15: "Allow users to bypass
        Content Production while still entering the same professional
        downstream pipeline." Only offered while no script exists yet
        - once imported, the script is edited through the exact same
        editor Content Production's own output uses (Phase 12).
        """

        layout.addWidget(separator())
        layout.addWidget(small_muted("Or import an already-written script:"))

        intake_editor = QTextEdit()
        intake_editor.setPlaceholderText(
            "Paste your script here (separate segments/paragraphs with "
            "a blank line)..."
        )
        intake_editor.setFixedHeight(120)
        self._script_intake_editor = intake_editor
        layout.addWidget(intake_editor)

        mode_row = QHBoxLayout()
        mode_select = QComboBox()
        for mode in ScriptIntakeMode:
            mode_select.addItem(mode.value.replace("_", " ").title(), mode)
        mode_select.setCurrentIndex(1)  # Validate for Production
        self._script_intake_mode_select = mode_select
        mode_row.addWidget(small_muted("Intake mode:"))
        mode_row.addWidget(mode_select)
        layout.addLayout(mode_row)

        buttons_row = QHBoxLayout()

        upload_button = button("Upload .txt file...", variant="ghost")
        upload_button.clicked.connect(self._handle_upload_script_file)
        buttons_row.addWidget(upload_button)

        import_button = button("Import script", variant="primary")
        import_button.clicked.connect(self._handle_import_script)
        buttons_row.addWidget(import_button)

        layout.addLayout(buttons_row)

    def _render_script_intake_summary(self, layout: QVBoxLayout, job: VideoJob) -> None:
        result = job.script_intake_result

        if result is None:
            return

        layout.addWidget(
            badge(
                f"Imported script [{result.mode.value}] · {result.word_count} words "
                f"· ~{result.estimated_duration_seconds:.0f}s narration "
                f"(target {result.target_duration_seconds}s)"
            )
        )
        layout.addWidget(
            small_muted(
                "This script was imported via Script Intake - Research, "
                "Hooks, and the Beat Sheet from Content Production are "
                "intentionally absent for it, not missing by mistake."
            )
        )

        if result.mismatches:
            for mismatch in result.mismatches:
                layout.addWidget(
                    status_label(
                        f"[{mismatch.field}] expected {mismatch.expected}, "
                        f"detected {mismatch.detected}: {mismatch.note}",
                        role="warning",
                    )
                )
        else:
            layout.addWidget(
                status_label("No project-setting mismatches detected.", role="success")
            )

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
        """
        Content Studio Redesign, Phase 13: Critique tab / formal
        Quality Gate. Separates the Reviewer's advisory critique
        (findings) from the system's own pass/fail decision - a
        finding is one input to this gate, never the sole authority
        (the LLM alone never decides Quality passes).
        """

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

        if (
            report.script_version_number is not None
            and job.script_version_history is not None
            and report.script_version_number
            != job.script_version_history.current_version.version_number
        ):
            layout.addWidget(
                status_label(
                    f"This result was computed against script v"
                    f"{report.script_version_number}, but the current "
                    f"version is v"
                    f"{job.script_version_history.current_version.version_number} "
                    "- it no longer reflects the script. Run the quality "
                    "gate again.",
                    role="warning",
                )
            )

        for dimension, threshold in sorted(report.dimension_thresholds.items()):
            score = report.dimension_scores.get(dimension, 0)
            passed = dimension not in report.failed_dimensions
            layout.addWidget(
                small_muted(
                    f"{'[pass]' if passed else '[fail]'} {dimension}: "
                    f"{score} (needs {threshold})"
                )
            )

        self._quality_finding_checkboxes = {}
        findings = report.all_findings

        if not findings:
            layout.addWidget(status_label("No findings.", role="success"))

            return True

        for finding in findings:
            resolution = report.resolution_for(finding.id)
            location = (
                f"segment {finding.segment_number}"
                if finding.segment_number is not None
                else "whole script"
            )
            safe_tag = "safe" if finding.is_safe_to_auto_fix else "needs review"

            if resolution is not None:
                layout.addWidget(
                    small_muted(
                        f"[{finding.severity.value} · {location} · "
                        f"{resolution.action.value}"
                        + (f": {resolution.reason}" if resolution.reason else "")
                        + f"] {finding.problem}"
                    )
                )

                continue

            checkbox = QCheckBox(
                f"[{finding.severity.value} · {location} · {safe_tag}] "
                f"{finding.problem} -> {finding.recommended_correction}"
            )
            self._quality_finding_checkboxes[finding.id] = checkbox
            layout.addWidget(checkbox)

            ignore_row = QHBoxLayout()
            reason_input = QLineEdit()
            reason_input.setPlaceholderText("Reason for ignoring...")
            ignore_row.addWidget(reason_input)
            ignore_button = button("Ignore with reason", variant="ghost")
            ignore_button.clicked.connect(
                lambda _checked=False, fid=finding.id, inp=reason_input: (
                    self._handle_ignore_quality_finding(fid, inp)
                )
            )
            ignore_row.addWidget(ignore_button)
            layout.addLayout(ignore_row)

        actions_row = QHBoxLayout()

        apply_selected_button = button("Apply selected fixes", variant="primary")
        apply_selected_button.clicked.connect(self._handle_apply_selected_fixes)
        actions_row.addWidget(apply_selected_button)

        fix_all_safe_button = button("Fix all safe issues", variant="ghost")
        fix_all_safe_button.clicked.connect(self._handle_fix_all_safe_issues)
        actions_row.addWidget(fix_all_safe_button)

        return_button = button("Return to script", variant="ghost")
        return_button.clicked.connect(self._handle_return_to_script)
        actions_row.addWidget(return_button)

        layout.addLayout(actions_row)

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
        """
        Content Studio Redesign, Phase 12: Versions tab (V1/V2/V3,
        Compare, Restore) - each version shows its reason (generation/
        manual edit/reviewer revision/quality fix/restore) alongside
        the existing change-class/lock display, every non-current
        version gets a Restore button, and two selectors plus a
        Compare button render a full segment-by-segment diff.
        """

        history = job.script_version_history

        if history is None:
            return

        layout.addWidget(badge(f"{len(history.versions)} version(s)"))

        ordered_versions = sorted(history.versions, key=lambda v: v.version_number)
        current = history.current_version

        for version in ordered_versions:
            change = version.change_class.value if version.change_class else "initial"
            reason = version.reason.value if version.reason else "unknown"
            lock_tag = " [locked]" if version.locked else ""
            layout.addWidget(
                small_muted(
                    f"v{version.version_number} [{change}, {reason}]"
                    f"{lock_tag}: {version.change_summary}"
                )
            )

            if version.version_number != current.version_number:
                restore_button = button(
                    f"Restore v{version.version_number}", variant="ghost"
                )
                restore_button.clicked.connect(
                    lambda _checked=False, num=version.version_number: (
                        self._handle_restore_script_version(num)
                    )
                )
                layout.addWidget(restore_button, alignment=_LEFT)

        lock_button = button(
            "Unlock current version" if current.locked else "Lock current version",
            variant="ghost",
        )
        lock_button.clicked.connect(self._handle_toggle_script_version_lock)
        layout.addWidget(lock_button, alignment=_LEFT)

        if len(ordered_versions) > 1:
            layout.addWidget(small_muted("Compare versions:"))
            compare_row = QHBoxLayout()

            from_select = QComboBox()
            to_select = QComboBox()

            for version in ordered_versions:
                from_select.addItem(
                    f"v{version.version_number}", version.version_number
                )
                to_select.addItem(f"v{version.version_number}", version.version_number)

            to_select.setCurrentIndex(len(ordered_versions) - 1)

            self._script_compare_from = from_select
            self._script_compare_to = to_select

            compare_row.addWidget(from_select)
            compare_row.addWidget(small_muted("vs"))
            compare_row.addWidget(to_select)

            compare_button = button("Compare", variant="ghost")
            compare_button.clicked.connect(self._handle_compare_script_versions)
            compare_row.addWidget(compare_button)
            layout.addLayout(compare_row)

            comparison = self._last_script_comparison

            if comparison is not None:
                layout.addWidget(
                    badge(
                        f"v{comparison.from_version_number} vs "
                        f"v{comparison.to_version_number}: "
                        + ("changes found" if comparison.has_changes else "no changes")
                    )
                )

                for diff in comparison.segment_diffs:
                    if diff.status == "unchanged":
                        continue

                    layout.addWidget(
                        small_muted(
                            f"Segment {diff.segment_number} [{diff.status}]: "
                            f"{diff.narration_before or '(none)'} -> "
                            f"{diff.narration_after or '(none)'}"
                        )
                    )

        self._render_script_lock_section(layout, job)

        layout.addWidget(separator())

    def _render_script_lock_section(self, layout: QVBoxLayout, job: VideoJob) -> None:
        """
        Content Studio Redesign, Phase 14: Script Lock - the hard
        boundary between Content Production and Media Production.
        Distinct from the lightweight per-version lock toggle above
        (which just blocks further edits): this records a full
        ScriptLock (version, hash, provenance, quality status
        snapshot) and is what "Media Production can start using only
        the lock/handoff contract" actually refers to.
        """

        layout.addWidget(separator())
        lock = job.script_lock

        if lock is None:
            report = job.script_quality_report
            has_unresolved = bool(
                report is not None and report.unresolved_blocking_findings
            )

            if has_unresolved:
                layout.addWidget(
                    status_label(
                        f"{len(report.unresolved_blocking_findings)} unresolved "  # type: ignore[union-attr]
                        "blocking quality finding(s) - locking requires "
                        "resolving them or an override reason below.",
                        role="warning",
                    )
                )

            override_input = QLineEdit()
            override_input.setPlaceholderText(
                "Override reason (only needed if blocking findings remain)..."
            )
            layout.addWidget(override_input)

            lock_button = button("Approve & lock script", variant="primary")
            lock_button.clicked.connect(
                lambda _checked=False, inp=override_input: (
                    self._handle_lock_script(inp)
                )
            )
            layout.addWidget(lock_button, alignment=_LEFT)

            return

        layout.addWidget(
            status_label(
                f"Script locked at v{lock.script_version_number} "
                f"[{lock.provenance.value}]"
                + (
                    f", quality: {lock.quality_status.value}"
                    if lock.quality_status is not None
                    else ""
                )
                + (
                    f" (override: {lock.override_reason})"
                    if lock.override_reason
                    else ""
                ),
                role="success",
            )
        )
        layout.addWidget(
            small_muted(f"Content hash: {lock.script_content_hash[:16]}...")
        )

        unlock_button = button("Unlock script", variant="ghost")
        unlock_button.clicked.connect(self._handle_unlock_script)
        layout.addWidget(unlock_button, alignment=_LEFT)

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

    def _render_production_readiness_panel(
        self, layout: QVBoxLayout, job: VideoJob
    ) -> bool:
        """
        Content Studio Redesign, Phase 16: "Production Enrichment
        review screen" - most of this phase's directive-generation
        deliverables already run identically for any script via the
        pre-existing continuity bible / scene planning / genre
        directive machinery; this panel is specifically the
        ambiguity-registry + readiness-summary piece that's genuinely
        new. "Run production readiness" (the generic per-stage button
        below) triggers ambiguity detection.
        """

        if job.generated_script is None:
            layout.addWidget(small_muted("Requires a generated script first."))

            return False

        readiness = (
            self._content_intelligence_pipeline.compute_script_production_readiness(job)
        )

        layout.addWidget(
            status_label(
                "Ready for production" if readiness.is_ready else "Not yet ready",
                role="success" if readiness.is_ready else "warning",
            )
        )
        layout.addWidget(
            small_muted(
                f"Continuity bible: {'yes' if readiness.has_continuity_bible else 'no'} "
                f"· Scenes: {readiness.scene_count}"
            )
        )

        if not job.production_ambiguities:
            layout.addWidget(
                small_muted(
                    "No ambiguities detected yet - run production readiness "
                    "to check."
                )
            )

            return True

        for ambiguity in job.production_ambiguities:
            critical_tag = (
                " [continuity-critical]" if ambiguity.continuity_critical else ""
            )

            if ambiguity.status.value != "unresolved":
                layout.addWidget(
                    small_muted(
                        f"[{ambiguity.status.value}]{critical_tag} "
                        f"{ambiguity.description} -> {ambiguity.resolution_note}"
                    )
                )

                continue

            layout.addWidget(small_muted(f"{critical_tag} {ambiguity.description}"))

            resolve_row = QHBoxLayout()
            note_input = QLineEdit()
            note_input.setPlaceholderText("Resolution note...")
            resolve_row.addWidget(note_input)

            resolve_manually_button = button("Resolve manually", variant="ghost")
            resolve_manually_button.clicked.connect(
                lambda _checked=False, aid=ambiguity.id, inp=note_input: (
                    self._handle_resolve_ambiguity_manually(aid, inp)
                )
            )
            resolve_row.addWidget(resolve_manually_button)

            let_ai_decide_button = button("Let AI decide", variant="ghost")
            let_ai_decide_button.clicked.connect(
                lambda _checked=False, aid=ambiguity.id: (
                    self._handle_resolve_ambiguity_by_ai(aid)
                )
            )
            resolve_row.addWidget(let_ai_decide_button)

            layout.addLayout(resolve_row)

        return True

    def _handle_resolve_ambiguity_manually(
        self, ambiguity_id: UUID, note_input: QLineEdit
    ) -> None:
        note = note_input.text().strip()

        if not note:
            return

        job = self._current_job()

        if job is None:
            return

        try:
            self._content_intelligence_pipeline.run_resolve_ambiguity_manually(
                job, ambiguity_id=ambiguity_id, note=note
            )
        except ValueError as error:
            self._record_error(job, f"Could not resolve ambiguity: {error}")

            return

        self._on_change()

    def _handle_resolve_ambiguity_by_ai(self, ambiguity_id: UUID) -> None:
        job = self._current_job()

        if job is None:
            return

        try:
            self._content_intelligence_pipeline.run_resolve_ambiguity_by_ai(
                job, ambiguity_id=ambiguity_id
            )
        except (RuntimeError, ValueError) as error:
            self._record_error(job, f"Could not resolve ambiguity: {error}")

            return

        self._on_change()

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
            "writing_directives": (
                self._content_intelligence_pipeline.run_writing_directives
            ),
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
            "production_readiness": (
                self._content_intelligence_pipeline.run_production_ambiguity_detection
            ),
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

    def _handle_script_selection_edit(
        self, segment_number: int, operation: SelectionEditOperation
    ) -> None:
        self._apply_script_selection_edit(
            segment_number, operation, custom_instruction=None
        )

    def _handle_script_custom_selection_edit(
        self, segment_number: int, instruction_input: QLineEdit
    ) -> None:
        instruction = instruction_input.text().strip()

        if not instruction:
            return

        self._apply_script_selection_edit(
            segment_number,
            SelectionEditOperation.CUSTOM,
            custom_instruction=instruction,
        )
        instruction_input.clear()

    def _apply_script_selection_edit(
        self,
        segment_number: int,
        operation: SelectionEditOperation,
        *,
        custom_instruction: str | None,
    ) -> None:
        """
        Content Studio Redesign, Phase 12: apply one selection-scoped
        AI edit action. selected_text comes from whatever is currently
        highlighted in that segment's editor - QTextEdit represents a
        selection spanning multiple paragraphs with a U+2029 separator
        instead of "\\n", so that's normalized back before it reaches
        the "must be an exact substring of the narration" check in
        ScriptSelectionEditService.
        """

        job = self._current_job()

        if job is None or job.generated_script is None:
            return

        editor = self._script_segment_editors.get(segment_number)
        selected_text = None

        if editor is not None:
            raw_selection = (
                editor.textCursor().selectedText().replace(" ", "\n").strip()
            )
            selected_text = raw_selection or None

        try:
            request = SelectionEditRequest(
                segment_number=segment_number,
                operation=operation,
                selected_text=selected_text,
                custom_instruction=custom_instruction,
            )
            self._content_intelligence_pipeline.run_script_selection_edit(
                job, request=request
            )
        except (RuntimeError, ValueError) as error:
            self._record_error(
                job,
                f"Selection edit failed: {error}",
                on_retry=lambda: self._apply_script_selection_edit(
                    segment_number, operation, custom_instruction=custom_instruction
                ),
            )

            return

        self._on_change()

    def _handle_save_script_segment_edit(self, segment_number: int) -> None:
        """
        Record a person's own directly typed rewrite as a manual-edit
        version - no LLM call, unlike the selection-action buttons
        above. A no-op when the text is unchanged.

        The Save button itself is never rendered while locked (see
        _render_ci_script_panel), but this checks again directly -
        Phase 14: "Cannot silently edit locked script" means this
        handler must refuse on its own, not only rely on the button
        it's normally reached through being hidden.
        """

        job = self._current_job()

        if job is None or job.generated_script is None:
            return

        if (
            job.script_version_history is not None
            and job.script_version_history.is_locked
        ):
            return

        editor = self._script_segment_editors.get(segment_number)

        if editor is None:
            return

        new_text = editor.toPlainText().strip()

        if not new_text:
            return

        segments = job.generated_script.segments
        target = next(
            (
                segment
                for segment in segments
                if segment.segment_number == segment_number
            ),
            None,
        )

        if target is None or target.narration == new_text:
            return

        revised_target = target.model_copy(update={"narration": new_text})
        revised_segments = [
            revised_target if segment.segment_number == segment_number else segment
            for segment in segments
        ]
        job.generated_script = job.generated_script.model_copy(
            update={"segments": revised_segments}
        )

        if job.script_version_history is not None:
            service = self._content_intelligence_pipeline.script_version_service

            try:
                job.script_version_history = service.add_manual_edit(
                    history=job.script_version_history,
                    revised_script=job.generated_script,
                    change_summary=f"Segment {segment_number}: manual text edit.",
                )
            except ValueError as error:
                self._record_error(
                    job,
                    f"Could not save the edit: {error}",
                    on_retry=lambda: self._handle_save_script_segment_edit(
                        segment_number
                    ),
                )

                return

        # The prior critique/quality report describes the pre-edit
        # script - clear both, matching every other script-mutating
        # pipeline path (Phase 13: invalidation applies uniformly).
        job.editorial_critique = None
        job.script_quality_report = None

        # Found via external audit: this GUI-only, non-LLM path never
        # called InvalidationService, unlike run_revision()/
        # run_script_selection_edit()/run_script_restore() right next
        # to it - a person could retype a segment's narration after
        # scenes/clips/timelines/render already existed and none of
        # them would be flagged stale. Matching every other
        # script-mutating path for real now, not just in a comment.
        self._content_intelligence_pipeline.invalidation_service.on_script_changed(
            job,
            reason=(f"Segment {segment_number}'s narration was manually edited."),
        )

        self._on_change()

    def _handle_restore_script_version(self, version_number: int) -> None:
        job = self._current_job()

        if job is None:
            return

        try:
            self._content_intelligence_pipeline.run_script_restore(
                job, version_number=version_number
            )
        except (RuntimeError, ValueError) as error:
            self._record_error(
                job,
                f"Could not restore version {version_number}: {error}",
                on_retry=lambda: self._handle_restore_script_version(version_number),
            )

            return

        self._on_change()

    def _handle_compare_script_versions(self) -> None:
        job = self._current_job()

        if (
            job is None
            or job.script_version_history is None
            or self._script_compare_from is None
            or self._script_compare_to is None
        ):
            return

        from_number = self._script_compare_from.currentData()
        to_number = self._script_compare_to.currentData()

        if from_number is None or to_number is None:
            return

        service = self._content_intelligence_pipeline.script_version_service

        try:
            comparison = service.compare(
                history=job.script_version_history,
                from_version_number=from_number,
                to_version_number=to_number,
            )
        except ValueError as error:
            self._record_error(job, f"Could not compare versions: {error}")

            return

        self._last_script_comparison = comparison
        self._on_change()

    def _handle_ignore_quality_finding(
        self, finding_id: UUID, reason_input: QLineEdit
    ) -> None:
        reason = reason_input.text().strip()

        if not reason:
            return

        job = self._current_job()

        if job is None:
            return

        try:
            self._content_intelligence_pipeline.run_ignore_finding(
                job, finding_id=finding_id, reason=reason
            )
        except (RuntimeError, ValueError) as error:
            self._record_error(job, f"Could not ignore finding: {error}")

            return

        self._on_change()

    def _handle_apply_selected_fixes(self) -> None:
        job = self._current_job()

        if job is None:
            return

        selected_ids = [
            finding_id
            for finding_id, checkbox in self._quality_finding_checkboxes.items()
            if checkbox.isChecked()
        ]

        if not selected_ids:
            return

        try:
            self._content_intelligence_pipeline.run_revision(
                job, finding_ids=selected_ids
            )
        except (RuntimeError, ValueError) as error:
            self._record_error(job, f"Could not apply selected fixes: {error}")

            return

        self._on_change()

    def _handle_fix_all_safe_issues(self) -> None:
        job = self._current_job()

        if job is None or job.script_quality_report is None:
            return

        report = job.script_quality_report
        safe_ids = [
            finding.id
            for finding in report.all_findings
            if finding.is_safe_to_auto_fix and report.resolution_for(finding.id) is None
        ]

        if not safe_ids:
            return

        try:
            self._content_intelligence_pipeline.run_revision(job, finding_ids=safe_ids)
        except (RuntimeError, ValueError) as error:
            self._record_error(job, f"Could not fix safe issues: {error}")

            return

        self._on_change()

    def _handle_return_to_script(self) -> None:
        script_index = next(
            index for index, (key, _label) in enumerate(_CI_STAGES) if key == "script"
        )
        self._handle_select_ci_stage(script_index)

    def _handle_upload_script_file(self) -> None:
        """
        Content Studio Redesign, Phase 15: "paste/upload support" -
        reads a local .txt file's raw text into the same paste box
        Import Script reads from, rather than a separate upload path.
        Real document-format extraction (.docx/.pdf/...) is out of
        scope this pass; plain text covers the common case.
        """

        if self._script_intake_editor is None:
            return

        file_path, _filter = QFileDialog.getOpenFileName(
            self, "Upload script text file", "", "Text files (*.txt)"
        )

        if not file_path:
            return

        try:
            with open(file_path, encoding="utf-8") as handle:
                text = handle.read()
        except OSError as error:
            job = self._current_job()

            if job is not None:
                self._record_error(job, f"Could not read the file: {error}")

            return

        self._script_intake_editor.setPlainText(text)

    def _handle_import_script(self) -> None:
        """
        Content Studio Redesign, Phase 15: "Allow users to bypass
        Content Production while still entering the same professional
        downstream pipeline."
        """

        job = self._current_job()

        if (
            job is None
            or self._script_intake_editor is None
            or self._script_intake_mode_select is None
        ):
            return

        raw_text = self._script_intake_editor.toPlainText().strip()

        if not raw_text:
            return

        mode = self._script_intake_mode_select.currentData()

        if mode is None:
            mode = ScriptIntakeMode.VALIDATE_FOR_PRODUCTION

        try:
            self._content_intelligence_pipeline.run_script_intake(
                job, raw_text=raw_text, mode=mode
            )
        except (RuntimeError, ValueError) as error:
            self._record_error(job, f"Could not import script: {error}")

            return

        self._on_change()

    def _handle_lock_script(self, override_input: QLineEdit) -> None:
        """
        Content Studio Redesign, Phase 14: "Approve & Lock Script,"
        GUI requirement "Confirmation dialog before lock."
        """

        job = self._current_job()

        if job is None:
            return

        confirmation = QMessageBox.question(
            self,
            "Lock script",
            "Lock the current script version? Once locked, no further "
            "AI or manual edits are possible until it is explicitly "
            "unlocked.",
        )

        if confirmation != QMessageBox.StandardButton.Yes:
            return

        override_reason = override_input.text().strip() or None

        try:
            # provenance is left unset here - run_script_lock() infers
            # EXTERNAL vs INTERNAL from whether this project's script
            # came in through Script Intake (Phase 15) on its own.
            self._content_intelligence_pipeline.run_script_lock(
                job,
                override_reason=override_reason,
            )
        except ValueError as error:
            self._record_error(job, f"Could not lock script: {error}")

            return

        self._on_change()

    def _handle_unlock_script(self) -> None:
        """
        Content Studio Redesign, Phase 14: "Unlock impact analysis" -
        the confirmation lists the real dependent production assets,
        not a generic message.
        """

        job = self._current_job()

        if job is None:
            return

        impact = self._content_intelligence_pipeline.compute_script_unlock_impact(job)
        impact_text = (
            "This will mark the following existing production work as "
            f"stale: {', '.join(impact)}."
            if impact
            else "No downstream production work exists yet - nothing "
            "will be marked stale."
        )

        confirmation = QMessageBox.question(
            self,
            "Unlock script",
            f"Unlock the script for further editing? {impact_text}",
        )

        if confirmation != QMessageBox.StandardButton.Yes:
            return

        try:
            self._content_intelligence_pipeline.run_script_unlock(job)
        except RuntimeError as error:
            self._record_error(job, f"Could not unlock script: {error}")

            return

        self._on_change()

    def _build_legacy_pipeline_notice(self, job: VideoJob) -> None:
        """
        Content Studio Redesign, Phase 19: "Legacy GUI retirement/
        redirect plan." The panels below this notice ("Content
        workflow," "Research," "Script," "Originality review,"
        "Scenes") are the original ContentPipeline - still fully
        functional and deliberately left in place (no destructive
        rewrite, matching this whole redesign's own ground rules), but
        superseded by the Content Intelligence card above for any
        project using it. Rather than hiding or disabling the legacy
        actions - which could strand an in-progress legacy-pipeline
        project mid-flow - this is a plain, always-visible pointer so
        a person opening a new project chooses the current path
        deliberately instead of by accident.

        Suppressed once a project has clearly already committed to one
        path (either pipeline has produced something), since at that
        point the redirect has already served its purpose and would
        just be noise on every refresh.
        """

        if not self._should_show_legacy_pipeline_notice(job):
            return

        frame, layout = card("Which workflow should I use?", icon_name="dashboard")
        layout.addWidget(
            small_muted(
                "Use the Content Intelligence card above - it is the current, "
                "actively developed production path (Audience Promise through "
                "Script Lock). The 'Content workflow'/'Research'/'Script'/"
                "'Originality review'/'Scenes' panels below are the original "
                "pipeline, kept working for existing projects but not the "
                "recommended starting point for a new one."
            )
        )
        self._layout.addWidget(frame)

    @staticmethod
    def _should_show_legacy_pipeline_notice(job: VideoJob) -> bool:
        """
        False once a project has clearly already committed to one
        pipeline (either has produced something) - at that point the
        redirect has already served its purpose and would just be
        noise on every refresh. A plain predicate, not folded directly
        into _build_legacy_pipeline_notice, so it can be tested
        without depending on Qt's deferred widget-deletion timing.
        """

        return not (
            job.audience_promise is not None
            or job.generated_script is not None
            or job.research is not None
            or job.script is not None
        )

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
            scenes = self._content_pipeline.scene_planner.plan(
                job.script, genre_id=job.genre_id
            )
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
