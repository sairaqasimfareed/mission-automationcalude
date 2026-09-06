from __future__ import annotations

from uuid import UUID

from src.agents.research_agent.agent import ResearchAgent
from src.agents.scene_planner.agent import ScenePlannerAgent
from src.models.approval import ApprovalDecision, HumanApprovalAction
from src.models.automation_status import AutomationStatus
from src.models.content_decision_record import DecisionCategory
from src.models.editorial_profile import EditorialProfile
from src.models.information_reveal_map import InformationRevealMap
from src.models.production_handoff import (
    ProductionHandoffState,
    ProductionHandoffStatus,
)
from src.models.script_intake import ScriptIntakeMode
from src.models.script_lock import ScriptProvenance
from src.models.script_production_readiness import ScriptProductionReadinessReport
from src.models.script_quality_report import ScriptQualityStatus
from src.models.script_selection_edit import SelectionEditRequest
from src.models.story_blueprint import StoryBeatType, StoryBlueprint
from src.models.video_job import VideoJob
from src.services.approval_gate_service import ApprovalGateService
from src.services.audience_promise_service import AudiencePromiseService
from src.services.continuity_bible_extraction_service import (
    ContinuityBibleExtractionService,
)
from src.services.continuity_validation_service import ContinuityValidationService
from src.services.editorial_critique_service import EditorialCritiqueService
from src.services.editorial_profile_composition_service import (
    EditorialProfileCompositionService,
)
from src.services.genre_profile_registry_service import (
    GenreProfileRegistryService,
)
from src.services.hook_evaluation_service import (
    HookEvaluationService,
    select_winning_hook,
)
from src.services.hook_generation_service import HookGenerationService
from src.services.information_reveal_planning_service import (
    InformationRevealPlanningService,
)
from src.services.invalidation_service import InvalidationService
from src.services.llm.llm_service import LLMService
from src.services.narrative_compression_service import NarrativeCompressionService
from src.services.packaging_hypothesis_service import PackagingHypothesisService
from src.services.production_ambiguity_service import ProductionAmbiguityService
from src.services.production_semantic_brief_service import (
    ProductionSemanticBriefService,
)
from src.services.re_hook_planning_service import ReHookPlanningService
from src.services.research_planning_service import ResearchPlanningService
from src.services.retention_audit_service import RetentionAuditService
from src.services.script_generation_service import ScriptGenerationService
from src.services.script_intake_service import ScriptIntakeService
from src.services.script_lock_service import ScriptLockService
from src.services.script_production_readiness_service import (
    ScriptProductionReadinessService,
)
from src.services.script_quality_gate_service import ScriptQualityGateService
from src.services.script_revision_service import ScriptRevisionService
from src.services.script_selection_edit_service import ScriptSelectionEditService
from src.services.script_version_service import ScriptVersionService
from src.services.story_angle_evaluation_service import (
    StoryAngleEvaluationService,
    select_winning_evaluation,
)
from src.services.story_angle_generation_service import StoryAngleGenerationService
from src.services.story_blueprint_generation_service import (
    StoryBlueprintGenerationService,
)
from src.services.writing_directives_service import WritingDirectivesService


class ContentIntelligencePipeline:
    """
    Runs the genre-aware Content Intelligence engine: audience promise
    through script generation (sprints 2-7, retrofitted genre-aware in
    Sprint A3).

    Mirrors ContentPipeline's own convention - each stage is a
    separate, explicitly triggered method rather than one atomic call,
    so a GUI can gate progress on human approval between stages
    (Sprint A8) instead of hiding everything inside one big .run().
    The older ContentPipeline/ResearchAgent/ScriptAgent path is left
    untouched; this pipeline writes to a distinct set of VideoJob
    fields (audience_promise, story_angles, story_blueprint,
    generated_script, ...) alongside it.
    """

    def __init__(
        self,
        *,
        llm_service: LLMService,
        genre_registry: GenreProfileRegistryService | None = None,
        research_agent: ResearchAgent | None = None,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        self.genre_registry = (
            genre_registry or GenreProfileRegistryService.with_default_profiles()
        )
        self.composition_service = EditorialProfileCompositionService()
        self.research_agent = research_agent or ResearchAgent(
            llm_service=llm_service,
            profile_ids=profile_ids,
            estimated_cost_usd=estimated_cost_usd,
        )

        self.audience_promise_service = AudiencePromiseService(
            llm_service=llm_service,
            profile_ids=profile_ids,
            estimated_cost_usd=estimated_cost_usd,
        )
        self.research_planning_service = ResearchPlanningService(
            llm_service=llm_service,
            profile_ids=profile_ids,
            estimated_cost_usd=estimated_cost_usd,
        )
        self.story_angle_generation_service = StoryAngleGenerationService(
            llm_service=llm_service,
            profile_ids=profile_ids,
            estimated_cost_usd=estimated_cost_usd,
        )
        self.story_angle_evaluation_service = StoryAngleEvaluationService(
            llm_service=llm_service,
            profile_ids=profile_ids,
            estimated_cost_usd=estimated_cost_usd,
        )
        self.information_reveal_planning_service = InformationRevealPlanningService(
            llm_service=llm_service,
            profile_ids=profile_ids,
            estimated_cost_usd=estimated_cost_usd,
        )
        self.story_blueprint_generation_service = StoryBlueprintGenerationService(
            llm_service=llm_service,
            profile_ids=profile_ids,
            estimated_cost_usd=estimated_cost_usd,
        )
        self.hook_generation_service = HookGenerationService(
            llm_service=llm_service,
            profile_ids=profile_ids,
            estimated_cost_usd=estimated_cost_usd,
        )
        self.hook_evaluation_service = HookEvaluationService(
            llm_service=llm_service,
            profile_ids=profile_ids,
            estimated_cost_usd=estimated_cost_usd,
        )
        self.re_hook_planning_service = ReHookPlanningService(
            llm_service=llm_service,
            profile_ids=profile_ids,
            estimated_cost_usd=estimated_cost_usd,
        )
        self.script_generation_service = ScriptGenerationService(
            llm_service=llm_service,
            profile_ids=profile_ids,
            estimated_cost_usd=estimated_cost_usd,
        )
        self.narrative_compression_service = NarrativeCompressionService(
            llm_service=llm_service,
            profile_ids=profile_ids,
            estimated_cost_usd=estimated_cost_usd,
        )
        self.retention_audit_service = RetentionAuditService()
        self.editorial_critique_service = EditorialCritiqueService(
            llm_service=llm_service,
            profile_ids=profile_ids,
            estimated_cost_usd=estimated_cost_usd,
        )
        self.script_revision_service = ScriptRevisionService(
            llm_service=llm_service,
            profile_ids=profile_ids,
            estimated_cost_usd=estimated_cost_usd,
        )
        self.script_selection_edit_service = ScriptSelectionEditService(
            llm_service=llm_service,
            profile_ids=profile_ids,
            estimated_cost_usd=estimated_cost_usd,
        )
        self.script_quality_gate_service = ScriptQualityGateService()
        self.packaging_hypothesis_service = PackagingHypothesisService(
            llm_service=llm_service,
            profile_ids=profile_ids,
            estimated_cost_usd=estimated_cost_usd,
        )
        self.scene_planner = ScenePlannerAgent()
        self.script_version_service = ScriptVersionService()
        self.script_lock_service = ScriptLockService()
        self.script_intake_service = ScriptIntakeService(
            llm_service=llm_service,
            profile_ids=profile_ids,
            estimated_cost_usd=estimated_cost_usd,
        )
        self.production_ambiguity_service = ProductionAmbiguityService(
            llm_service=llm_service,
            profile_ids=profile_ids,
            estimated_cost_usd=estimated_cost_usd,
        )
        self.script_production_readiness_service = ScriptProductionReadinessService()
        self.production_semantic_brief_service = ProductionSemanticBriefService()
        self.continuity_bible_extraction_service = ContinuityBibleExtractionService(
            llm_service=llm_service,
            profile_ids=profile_ids,
            estimated_cost_usd=estimated_cost_usd,
        )
        self.continuity_validation_service = ContinuityValidationService()
        self.writing_directives_service = WritingDirectivesService(
            llm_service=llm_service,
            profile_ids=profile_ids,
            estimated_cost_usd=estimated_cost_usd,
        )
        self.approval_gate_service = ApprovalGateService()
        self.invalidation_service = InvalidationService()

    def resolve_editorial_profile(self, job: VideoJob) -> EditorialProfile:
        """
        Resolve and cache the effective editorial profile for one job.

        Re-resolves every call rather than trusting a stale snapshot,
        but callers should generally read job.editorial_profile_snapshot
        after a stage runs instead of calling this directly.
        """

        resolution = self.genre_registry.resolve(job.genre_id)

        if not resolution.is_resolved or resolution.profile is None:
            raise RuntimeError(
                f"Could not resolve a usable genre profile for '{job.genre_id}'."
            )

        return self.composition_service.compose(genre=resolution.profile)

    def run_audience_promise(self, job: VideoJob) -> VideoJob:
        """Stage 1: resolve the genre profile and determine the audience promise."""

        editorial_profile = self.resolve_editorial_profile(job)
        job.editorial_profile_snapshot = editorial_profile

        job.audience_promise = self.audience_promise_service.determine(
            topic=job.topic,
            target_audience=job.target_audience,
            platform=job.platform.value,
            editorial_profile=editorial_profile,
            target_duration_seconds=job.target_duration_seconds,
        )

        self.approval_gate_service.gate(
            job=job,
            decision_point="content_strategy",
            stage="audience_promise",
            summary=f"Audience promise determined for '{job.topic}'.",
            confidence=job.audience_promise.confidence_score,
        )

        return job

    def run_research_plan(self, job: VideoJob) -> VideoJob:
        """Stage 2: plan what research questions this topic needs."""

        if job.audience_promise is None:
            raise RuntimeError("Research planning requires an audience promise.")

        editorial_profile = job.editorial_profile_snapshot or (
            self.resolve_editorial_profile(job)
        )

        plan = self.research_planning_service.plan(
            job.topic, job.audience_promise, editorial_profile
        )
        job.research_plan = plan

        # Content Studio Redesign, Phase 7: "No retrieval job starts
        # until brief approval/start action." confidence=None under
        # AUTO (this decision point's default - see
        # ApprovalPolicyConfig.research_plan) resolves immediately to
        # APPROVED, so this is a no-op for every existing AUTO/
        # full_auto() project; REVIEW/MANUAL modes make "Approve Brief
        # & Start Research" a real required GUI action instead.
        self.approval_gate_service.gate(
            job=job,
            decision_point="research_plan",
            stage="research_plan",
            summary=(
                f"Research brief planned for '{job.topic}' "
                f"({len(plan.research_questions)} question(s))."
            ),
        )

        return job

    def run_research(self, job: VideoJob) -> VideoJob:
        """
        Stage 3: execute research.

        Reuses the existing ResearchAgent unchanged - the research
        plan from stage 2 is upstream guidance for a human reviewer,
        not yet consumed by ResearchAgent itself (it only takes a
        topic). Making research genuinely plan-driven is future work
        (deeper multi-source research), not part of this convergence
        pass.
        """

        job.research = self.research_agent.research(job.topic)

        self.approval_gate_service.gate(
            job=job,
            decision_point="research",
            stage="research",
            summary=f"Research completed for '{job.topic}'.",
            confidence=job.research.fact_confidence_score / 100.0,
        )

        return job

    def run_story_angles(self, job: VideoJob) -> VideoJob:
        """Stage 4: generate and score candidate story angles."""

        if job.research is None or job.audience_promise is None:
            raise RuntimeError(
                "Story angle generation requires research and an audience promise."
            )

        editorial_profile = job.editorial_profile_snapshot or (
            self.resolve_editorial_profile(job)
        )

        angles = self.story_angle_generation_service.generate(
            topic=job.topic,
            research=job.research,
            audience_promise=job.audience_promise,
            editorial_profile=editorial_profile,
        )
        job.story_angles = angles

        evaluations = self.story_angle_evaluation_service.evaluate(
            topic=job.topic,
            angles=angles,
            research=job.research,
            editorial_profile=editorial_profile,
        )
        job.story_angle_evaluations = evaluations

        winner = select_winning_evaluation(evaluations)
        matched_angle = next(
            (angle for angle in angles if angle.title == winner.angle_title),
            angles[0],
        )
        job.selected_story_angle = matched_angle

        self.approval_gate_service.gate(
            job=job,
            decision_point="story_angle",
            stage="story_angles",
            summary=f"Selected story angle: '{matched_angle.title}'.",
            confidence=winner.confidence_score,
        )

        return job

    def run_narrative_architecture(
        self, job: VideoJob, *, additional_instructions: str | None = None
    ) -> VideoJob:
        """
        Stage 5: plan the reveal map and story blueprint.

        additional_instructions is optional free-text guidance for a
        targeted regeneration (Content Studio Redesign, Phase 9's "AI
        instruction example: compress slow middle section") - passed
        straight through to the blueprint generator, never mutating
        job.research (read-only input here, exactly as before this
        phase - "Architecture-only regeneration must not mutate
        Research").
        """

        if (
            job.selected_story_angle is None
            or job.research is None
            or job.audience_promise is None
        ):
            raise RuntimeError(
                "Narrative architecture requires a selected story angle, "
                "research, and an audience promise."
            )

        editorial_profile = job.editorial_profile_snapshot or (
            self.resolve_editorial_profile(job)
        )

        job.reveal_map = self.information_reveal_planning_service.plan(
            topic=job.topic,
            story_angle=job.selected_story_angle,
            research=job.research,
            editorial_profile=editorial_profile,
            target_duration_seconds=job.target_duration_seconds,
        )

        job.story_blueprint = self.story_blueprint_generation_service.generate(
            topic=job.topic,
            editorial_profile=editorial_profile,
            target_duration_seconds=job.target_duration_seconds,
            story_angle=job.selected_story_angle,
            audience_promise=job.audience_promise,
            research=job.research,
            additional_instructions=additional_instructions,
        )

        self._bind_curiosity_roles(job.story_blueprint, job.reveal_map)

        self.approval_gate_service.gate(
            job=job,
            decision_point="narrative_architecture",
            stage="narrative_architecture",
            summary=f"Story blueprint generated with {len(job.story_blueprint.beats)} beats.",
        )

        return job

    @staticmethod
    def _bind_curiosity_roles(
        blueprint: StoryBlueprint, reveal_map: InformationRevealMap
    ) -> None:
        """
        Content Studio Redesign, Phase 9: assign each StoryBeat's
        curiosity_loop_question ("curiosity/reveal role") by matching a
        loop's opened_at_position (normalized 0-1 across the whole
        story) against which beat's real-seconds time range contains
        that point. Deterministic position arithmetic, not narrative
        judgment - both the reveal map's positions and the blueprint's
        timings are already committed by the time this runs, so there
        is nothing for an LLM to decide here. Only the first
        not-yet-assigned beat containing a given loop's position is
        bound, so one beat is never silently overwritten by a second
        loop that happens to open at the same point.

        The interval check is half-open ([start, end)) for every beat
        except the last, which is closed on both ends - otherwise a
        loop opening at the very end of the story (opened_at_position
        == 1.0, landing exactly on the final beat's end_seconds) would
        satisfy no beat's range at all and silently go unbound (found
        via external audit).
        """

        if blueprint.target_duration_seconds <= 0:
            return

        ordered_beats = sorted(blueprint.beats, key=lambda beat: beat.start_seconds)

        for loop in reveal_map.curiosity_loops:
            loop_seconds = loop.opened_at_position * blueprint.target_duration_seconds

            for beat in ordered_beats:
                if beat.curiosity_loop_question is not None:
                    continue

                is_last_beat = beat is ordered_beats[-1]
                in_range = beat.start_seconds <= loop_seconds < beat.end_seconds
                at_final_edge = is_last_beat and loop_seconds >= beat.end_seconds

                if in_range or at_final_edge:
                    beat.curiosity_loop_question = loop.question

                    break

    def run_retention_audit(self, job: VideoJob) -> VideoJob:
        """
        Stage 5b: rule-based audit of the blueprint's reveal spacing
        and tension variation, before any prose is written on top of
        it. Advisory, not blocking - a thin blueprint is still usable
        (the editorial critics get a real chance to judge the finished
        prose later), but its findings should be visible before
        writing begins.
        """

        if job.story_blueprint is None:
            raise RuntimeError("Retention audit requires a story blueprint.")

        editorial_profile = job.editorial_profile_snapshot or (
            self.resolve_editorial_profile(job)
        )

        job.retention_audit = self.retention_audit_service.audit(
            topic=job.topic,
            blueprint=job.story_blueprint,
            editorial_profile=editorial_profile,
        )

        self.approval_gate_service.record_event(
            job=job,
            stage="retention_audit",
            summary="Retention audit generated.",
            category=DecisionCategory.GENERATION,
        )

        return job

    def run_hooks(
        self, job: VideoJob, *, additional_instructions: str | None = None
    ) -> VideoJob:
        """
        Stage 6: generate/score hooks and plan any scheduled re-hooks.

        additional_instructions is optional free-text guidance for a
        targeted regeneration ("Rewrite with Instructions" in the
        redesign's Hook Lab GUI), passed straight through to hook
        generation.
        """

        if (
            job.selected_story_angle is None
            or job.audience_promise is None
            or job.research is None
            or job.story_blueprint is None
        ):
            raise RuntimeError(
                "Hook generation requires a selected story angle, audience "
                "promise, research, and a story blueprint."
            )

        editorial_profile = job.editorial_profile_snapshot or (
            self.resolve_editorial_profile(job)
        )

        hooks = self.hook_generation_service.generate(
            topic=job.topic,
            story_angle=job.selected_story_angle,
            audience_promise=job.audience_promise,
            research=job.research,
            editorial_profile=editorial_profile,
            additional_instructions=additional_instructions,
        )
        job.hook_candidates = hooks

        evaluations = self.hook_evaluation_service.evaluate(
            topic=job.topic,
            hooks=hooks,
            research=job.research,
            editorial_profile=editorial_profile,
        )
        job.hook_evaluations = evaluations
        job.selected_hook = select_winning_hook(evaluations)

        has_re_hook_beats = any(
            beat.beat_type == StoryBeatType.RE_HOOK
            for beat in job.story_blueprint.beats
        )

        if has_re_hook_beats:
            job.re_hook_plan = self.re_hook_planning_service.plan(
                topic=job.topic,
                blueprint=job.story_blueprint,
                story_angle=job.selected_story_angle,
                editorial_profile=editorial_profile,
            )

        self.approval_gate_service.gate(
            job=job,
            decision_point="hook",
            stage="hooks",
            summary=f"Selected hook: '{job.selected_hook.hook_text}'.",
            confidence=job.selected_hook.confidence_score,
        )

        return job

    def run_writing_directives(self, job: VideoJob) -> VideoJob:
        """
        Stage 6b: resolve genre defaults, project rules, and user
        directives into one coherent Writing Directives set, after
        Hook and before Script (Content Studio Redesign, Phase 11).

        Not a hard requirement for run_script() - job.writing_directives
        stays None if this stage is never run, and script generation
        behaves exactly as it did before this phase existed.
        """

        if job.selected_hook is None:
            raise RuntimeError("Writing directives require a selected hook.")

        editorial_profile = job.editorial_profile_snapshot or (
            self.resolve_editorial_profile(job)
        )

        job.writing_directives = self.writing_directives_service.resolve(
            editorial_profile=editorial_profile,
            project_rules=job.project_writing_rules,
            user_directives=job.user_writing_directives,
        )

        self.approval_gate_service.record_event(
            job=job,
            stage="writing_directives",
            summary="Writing directives resolved.",
            category=DecisionCategory.GENERATION,
        )

        return job

    def run_script(self, job: VideoJob) -> VideoJob:
        """Stage 7: write and compress the script."""

        if (
            job.selected_hook is None
            or job.story_blueprint is None
            or job.reveal_map is None
            or job.research is None
            or job.audience_promise is None
            or job.selected_story_angle is None
        ):
            raise RuntimeError(
                "Script generation requires a selected hook, story "
                "blueprint, reveal map, research, audience promise, and "
                "a selected story angle."
            )

        editorial_profile = job.editorial_profile_snapshot or (
            self.resolve_editorial_profile(job)
        )

        script = self.script_generation_service.generate(
            topic=job.topic,
            editorial_profile=editorial_profile,
            research=job.research,
            audience_promise=job.audience_promise,
            story_angle=job.selected_story_angle,
            blueprint=job.story_blueprint,
            reveal_map=job.reveal_map,
            winning_hook=job.selected_hook,
            re_hook_plan=job.re_hook_plan,
            writing_directives=job.writing_directives,
        )

        job.generated_script = self.narrative_compression_service.compress(script)
        job.script_version_history = self.script_version_service.start_history(
            topic=job.topic,
            script=job.generated_script,
        )

        self.approval_gate_service.gate(
            job=job,
            decision_point="final_script",
            stage="script",
            summary=f"Script generated for '{job.topic}'.",
        )

        return job

    def run_continuity_bible(self, job: VideoJob) -> VideoJob:
        """
        Stage 7b: extract every character, location, timeline point,
        and standalone fact the script establishes, then flag any
        same-named entries whose descriptions disagree - advisory,
        like the retention audit, not a blocker on later stages.
        """

        if job.generated_script is None:
            raise RuntimeError(
                "Continuity bible extraction requires a generated script."
            )

        job.continuity_bible = self.continuity_bible_extraction_service.extract(
            job.generated_script
        )
        job.continuity_validation = self.continuity_validation_service.validate(
            job.continuity_bible
        )

        self.approval_gate_service.record_event(
            job=job,
            stage="continuity_bible",
            summary="Continuity bible extracted.",
            category=DecisionCategory.GENERATION,
        )

        return job

    def run_editorial_critique(self, job: VideoJob) -> VideoJob:
        """
        Stage 8: independent editorial critique of the finished
        script - a separate pass from writing, per the same
        discipline sprint 6/7's hook and angle evaluators follow.
        """

        if job.generated_script is None or job.research is None:
            raise RuntimeError(
                "Editorial critique requires a generated script and research."
            )

        editorial_profile = job.editorial_profile_snapshot or (
            self.resolve_editorial_profile(job)
        )

        job.editorial_critique = self.editorial_critique_service.critique(
            script=job.generated_script,
            research=job.research,
            editorial_profile=editorial_profile,
        )

        self.approval_gate_service.record_event(
            job=job,
            stage="editorial_critique",
            summary=f"Editorial critique generated ({len(job.editorial_critique.findings)} finding(s)).",
            category=DecisionCategory.GENERATION,
        )

        return job

    def run_quality_gate(self, job: VideoJob) -> VideoJob:
        """
        Stage 9: aggregate the critique against genre thresholds.

        Content Studio Redesign, Phase 13: the resulting report is
        bound to the exact script version/hash it was computed
        against, so a later script change can be told apart from a
        stale-but-still-displayed report.
        """

        if job.editorial_critique is None:
            raise RuntimeError("The quality gate requires an editorial critique.")

        editorial_profile = job.editorial_profile_snapshot or (
            self.resolve_editorial_profile(job)
        )

        job.script_quality_report = self.script_quality_gate_service.evaluate(
            critique=job.editorial_critique,
            editorial_profile=editorial_profile,
            script=job.generated_script,
            script_version_number=(
                job.script_version_history.current_version.version_number
                if job.script_version_history is not None
                else None
            ),
        )

        self.approval_gate_service.record_event(
            job=job,
            stage="quality_gate",
            summary=f"Quality gate evaluated: {job.script_quality_report.status.value}.",
            category=DecisionCategory.GENERATION,
        )

        return job

    def run_revision(
        self,
        job: VideoJob,
        *,
        finding_ids: list[UUID] | None = None,
    ) -> VideoJob:
        """
        Stage 10: revise the script to address the current critique's
        findings. The critique and quality report describe the
        pre-revision script, so both are cleared afterward - a fresh
        run_editorial_critique/run_quality_gate pass on the revised
        script is required before it can be approved.

        finding_ids is optional (Content Studio Redesign, Phase 13:
        "Apply Selected Fixes" vs "Fix All Safe Issues") - omitting it
        addresses every finding, reproducing this method's exact prior
        behavior.

        Checks the lock *before* calling the revision service (Phase
        14: "Cannot silently edit locked script") - ScriptVersionService
        .add_revision() also refuses a locked version, but only after
        job.generated_script would already have been overwritten by
        the LLM-revised text, corrupting it even though the version-
        history append then failed. Checking here first means a locked
        script is never touched at all.
        """

        if job.generated_script is None or job.editorial_critique is None:
            raise RuntimeError(
                "Script revision requires a generated script and an "
                "editorial critique."
            )

        if (
            job.script_version_history is not None
            and job.script_version_history.is_locked
        ):
            raise RuntimeError(
                "The current script version is locked - unlock it before " "revising."
            )

        critique = job.editorial_critique

        job.generated_script = self.script_revision_service.revise(
            script=job.generated_script,
            critique=critique,
            finding_ids=finding_ids,
        )

        if job.script_version_history is not None:
            job.script_version_history = self.script_version_service.add_revision(
                history=job.script_version_history,
                revised_script=job.generated_script,
                critique=critique,
            )

        job.editorial_critique = None
        job.script_quality_report = None

        self.approval_gate_service.record_event(
            job=job,
            stage="revision",
            summary="Script revised to address editorial critique findings.",
            category=DecisionCategory.GENERATION,
        )

        self.invalidation_service.on_script_changed(job)

        return job

    def run_ignore_finding(
        self,
        job: VideoJob,
        *,
        finding_id: UUID,
        reason: str,
    ) -> VideoJob:
        """
        Content Studio Redesign, Phase 13: "Store ignored findings
        with user reason." Does not touch the script or clear the
        quality report - ignoring a finding is a disposition on the
        finding itself, not a script change.
        """

        if job.script_quality_report is None:
            raise RuntimeError("There is no quality report to ignore a finding on.")

        job.script_quality_report = self.script_quality_gate_service.ignore_finding(
            report=job.script_quality_report,
            finding_id=finding_id,
            reason=reason,
        )

        self.approval_gate_service.record_event(
            job=job,
            stage="quality_gate",
            summary=f"Quality finding ignored: {reason}",
            category=DecisionCategory.GENERATION,
        )

        return job

    def run_script_selection_edit(
        self,
        job: VideoJob,
        *,
        request: SelectionEditRequest,
    ) -> VideoJob:
        """
        Content Studio Redesign, Phase 12: apply one selection-scoped
        AI edit (Rewrite/Shorten/Expand/More Suspenseful/More
        Natural/Improve Transition/Custom Instruction) to a single
        script segment, on a person's direct request - distinct from
        run_revision, which applies a whole EditorialCritique. Records
        one new manual-edit version. Any existing critique/quality-gate
        report describes the pre-edit script, so both are cleared here
        too, exactly like run_revision does (Phase 13: "Quality result
        invalidation after script change" applies to every script-
        mutating path, not only the critique-driven one).
        """

        if job.generated_script is None:
            raise RuntimeError("A selection edit requires a generated script.")

        if (
            job.script_version_history is not None
            and job.script_version_history.is_locked
        ):
            raise RuntimeError(
                "The current script version is locked - unlock it before "
                "making a selection edit."
            )

        revised_script, change_summary = self.script_selection_edit_service.edit(
            script=job.generated_script,
            request=request,
            writing_directives=job.writing_directives,
        )

        job.generated_script = revised_script

        if job.script_version_history is not None:
            job.script_version_history = self.script_version_service.add_manual_edit(
                history=job.script_version_history,
                revised_script=revised_script,
                change_summary=change_summary,
            )

        job.editorial_critique = None
        job.script_quality_report = None

        self.approval_gate_service.record_event(
            job=job,
            stage="script",
            summary=f"Selection edit applied: {change_summary}",
            category=DecisionCategory.GENERATION,
        )

        self.invalidation_service.on_script_changed(job)

        return job

    def run_script_restore(
        self,
        job: VideoJob,
        *,
        version_number: int,
    ) -> VideoJob:
        """
        Content Studio Redesign, Phase 12: restore an earlier script
        version's content as a new version (never destructive - the
        restored-from version, and everything in between, remains in
        history exactly as it was). Any existing critique/quality-gate
        report describes the pre-restore script, so both are cleared
        here too (Phase 13: invalidation applies to every script-
        mutating path).
        """

        if job.script_version_history is None:
            raise RuntimeError("This project has no script version history yet.")

        job.script_version_history = self.script_version_service.restore_version(
            history=job.script_version_history,
            version_number=version_number,
        )
        job.generated_script = job.script_version_history.current_version.script

        job.editorial_critique = None
        job.script_quality_report = None

        self.approval_gate_service.record_event(
            job=job,
            stage="script",
            summary=f"Restored script version {version_number} as a new version.",
            category=DecisionCategory.RESTORE,
        )

        self.invalidation_service.on_script_changed(job)

        return job

    def run_script_intake(
        self,
        job: VideoJob,
        *,
        raw_text: str,
        mode: ScriptIntakeMode = ScriptIntakeMode.VALIDATE_FOR_PRODUCTION,
    ) -> VideoJob:
        """
        Content Studio Redesign, Phase 15: "Allow users to bypass
        Content Production while still entering the same professional
        downstream pipeline." Builds a canonical GeneratedScript from
        raw pasted/uploaded text and starts a fresh version history for
        it - from this point on, every other script-touching stage
        (selection edits, revision, quality gate, lock) works
        identically whether the script came from Content Production or
        Script Intake. Deliberately does not touch research/story
        angle/hook/blueprint fields - an imported script has none of
        those, and none are fabricated to satisfy some other stage's
        input requirements.
        """

        if (
            job.script_version_history is not None
            and job.script_version_history.is_locked
        ):
            raise RuntimeError(
                "The current script version is locked - unlock it before "
                "importing a new one."
            )

        result = self.script_intake_service.intake(
            job=job, raw_text=raw_text, mode=mode
        )

        job.generated_script = result.script
        job.script_version_history = self.script_version_service.start_history(
            topic=job.topic, script=result.script
        )
        job.script_intake_result = result
        job.editorial_critique = None
        job.script_quality_report = None
        job.script_lock = None

        self.approval_gate_service.record_event(
            job=job,
            stage="script_intake",
            summary=(
                "Script imported via Script Intake "
                f"({getattr(mode, 'value', mode)})."
            ),
            category=DecisionCategory.GENERATION,
        )

        self.invalidation_service.on_script_changed(
            job, reason="A new script was imported via Script Intake."
        )

        return job

    def run_script_lock(
        self,
        job: VideoJob,
        *,
        provenance: ScriptProvenance | None = None,
        override_reason: str | None = None,
    ) -> VideoJob:
        """
        Content Studio Redesign, Phase 14: "Approve & Lock Script" -
        the hard, immutable boundary between Content Production and
        Media Production. Composes ScriptLockService (builds/validates
        the ScriptLock record) with the pre-existing ScriptVersionService
        per-version lock flag (the mechanism every script-mutating
        method already checks), rather than introducing a second,
        independent lock state.

        provenance defaults to EXTERNAL when this project's script
        came in through Script Intake (Phase 15) and INTERNAL
        otherwise - a caller only needs to pass it explicitly to
        override that inference.
        """

        resolved_provenance = provenance or (
            ScriptProvenance.EXTERNAL
            if job.script_intake_result is not None
            else ScriptProvenance.INTERNAL
        )

        lock = self.script_lock_service.build_lock(
            job=job, provenance=resolved_provenance, override_reason=override_reason
        )

        assert job.script_version_history is not None  # build_lock guarantees this

        job.script_version_history = self.script_version_service.lock_version(
            history=job.script_version_history,
            version_number=lock.script_version_number,
        )
        job.script_lock = lock

        self.approval_gate_service.record_event(
            job=job,
            stage="script_lock",
            summary=(
                f"Script locked for production (version {lock.script_version_number}, "
                f"{resolved_provenance.value})."
            ),
            category=DecisionCategory.LOCK,
            metadata={"script_version_number": lock.script_version_number},
        )

        return job

    def run_script_unlock(self, job: VideoJob) -> VideoJob:
        """
        Content Studio Redesign, Phase 14: reopens a locked script.
        Deliberately does not itself decide whether the caller should
        proceed - compute_script_unlock_impact() is how a GUI (or any
        other caller) gets the real list of dependent production
        assets to warn about *before* calling this.
        """

        if job.script_lock is None:
            raise RuntimeError("This project's script is not locked.")

        unlocked_version_number = job.script_lock.script_version_number

        if job.script_version_history is not None:
            job.script_version_history = self.script_version_service.unlock_version(
                history=job.script_version_history,
                version_number=unlocked_version_number,
            )

        job.script_lock = None

        self.approval_gate_service.record_event(
            job=job,
            stage="script_lock",
            summary=f"Script unlocked (was locked at version {unlocked_version_number}).",
            category=DecisionCategory.UNLOCK,
            metadata={"script_version_number": unlocked_version_number},
        )

        return job

    def compute_script_unlock_impact(self, job: VideoJob) -> list[str]:
        """
        Content Studio Redesign, Phase 14: "Unlock impact analysis" -
        the real VideoJob field names currently holding a production
        artifact that depends on the locked script, not a generic
        message.
        """

        return self.script_lock_service.compute_unlock_impact(job)

    def run_production_semantic_brief(self, job: VideoJob) -> VideoJob:
        """
        Post-Script-Approval Production Plan, Phase 1: "Translate the
        locked narrative into time-bounded production intent before
        any media is generated." Unlike every Content Studio
        Redesign stage above, this one hard-requires a script lock
        (job.script_lock is not None) rather than merely a generated
        script - this plan's whole chain hangs off the lock, not off
        the script directly, since "primary inputs: FinalScriptLock"
        is this phase's own stated contract.
        """

        if job.generated_script is None or job.script_lock is None:
            raise RuntimeError("Production semantic brief requires a locked script.")

        genre_resolution = self.genre_registry.resolve(job.genre_id)

        if genre_resolution.profile is None:
            raise RuntimeError(
                f"Could not resolve a genre profile for '{job.genre_id}'."
            )

        job.production_semantic_brief = self.production_semantic_brief_service.generate(
            script=job.generated_script,
            genre_profile=genre_resolution.profile,
            script_lock_hash=job.script_lock.script_content_hash,
            story_blueprint=job.story_blueprint,
        )

        self.approval_gate_service.record_event(
            job=job,
            stage="production_semantic_brief",
            summary=(
                "Production semantic brief generated "
                f"({len(job.production_semantic_brief.segments)} segment(s))."
            ),
            category=DecisionCategory.GENERATION,
        )

        return job

    def run_packaging_hypothesis(self, job: VideoJob) -> VideoJob:
        """
        Stage 11: propose a packaging direction for the finished
        script - thin and late, deliberately not real titles or
        thumbnails (see PackagingHypothesisService).
        """

        if job.generated_script is None or job.selected_hook is None:
            raise RuntimeError(
                "Packaging hypothesis requires a generated script and a "
                "selected hook."
            )

        editorial_profile = job.editorial_profile_snapshot or (
            self.resolve_editorial_profile(job)
        )

        job.packaging_hypothesis = self.packaging_hypothesis_service.generate(
            topic=job.topic,
            script=job.generated_script,
            selected_hook=job.selected_hook,
            editorial_profile=editorial_profile,
        )

        self.approval_gate_service.record_event(
            job=job,
            stage="packaging_hypothesis",
            summary="Packaging hypothesis generated.",
            category=DecisionCategory.GENERATION,
        )

        return job

    def run_scene_planning(self, job: VideoJob) -> VideoJob:
        """
        Stage 12: break the finished script into genre-aware scenes
        (see ScenePlannerAgent.plan_from_generated_script). Writes to
        the same job.scenes field the legacy ContentPipeline's
        sentence-split planner writes to - the two are mutually
        exclusive paths for one project, not two separate artifacts.
        """

        if job.generated_script is None:
            raise RuntimeError("Scene planning requires a generated script.")

        editorial_profile = job.editorial_profile_snapshot or (
            self.resolve_editorial_profile(job)
        )

        job.scenes = self.scene_planner.plan_from_generated_script(
            job.generated_script,
            editorial_profile,
        )

        if job.script_lock is not None:
            # Post-Script-Approval Production Plan, Phase 0: "All
            # downstream artifacts identify the exact locked script
            # SHA-256." Stamped here rather than inside ScenePlannerAgent
            # itself - the agent only knows about the script, not the
            # lock, and every other lock-aware decision in this
            # pipeline already lives at the orchestration layer.
            for scene in job.scenes:
                scene.locked_script_hash = job.script_lock.script_content_hash

        self.invalidation_service.clear_stale(job, "scenes")

        self.approval_gate_service.record_event(
            job=job,
            stage="scene_planning",
            summary=f"Scenes generated ({len(job.scenes)}).",
            category=DecisionCategory.GENERATION,
        )

        return job

    def run_production_ambiguity_detection(self, job: VideoJob) -> VideoJob:
        """
        Content Studio Redesign, Phase 16: "Production Semantic
        analysis" / "Production ambiguity registry." Most of this
        phase's other deliverables (video/voice/editing directives)
        already work identically for any script regardless of origin
        via the pre-existing ContinuityBibleExtractionService,
        ScenePlannerAgent, and GenreDirectiveGenerationService/
        GenreVoiceDirectiveGenerationService - this method covers the
        one genuinely new piece: surfacing what the script's text
        leaves genuinely unresolved, rather than letting anything
        downstream silently invent an answer.
        """

        if job.generated_script is None:
            raise RuntimeError("Ambiguity detection requires a generated script.")

        new_ambiguities = self.production_ambiguity_service.detect(
            script=job.generated_script,
            continuity_bible=job.continuity_bible,
        )
        job.production_ambiguities = [
            *job.production_ambiguities,
            *new_ambiguities,
        ]

        self.approval_gate_service.record_event(
            job=job,
            stage="production_readiness",
            summary=f"Production ambiguity detection found {len(new_ambiguities)} new ambiguity(-ies).",
            category=DecisionCategory.GENERATION,
        )

        return job

    def run_resolve_ambiguity_manually(
        self,
        job: VideoJob,
        *,
        ambiguity_id: UUID,
        note: str,
    ) -> VideoJob:
        job.production_ambiguities = [
            (
                self.production_ambiguity_service.resolve_manually(
                    ambiguity=ambiguity, note=note
                )
                if ambiguity.id == ambiguity_id
                else ambiguity
            )
            for ambiguity in job.production_ambiguities
        ]

        self.approval_gate_service.record_event(
            job=job,
            stage="production_readiness",
            summary=f"Production ambiguity resolved manually: {note}",
            category=DecisionCategory.GENERATION,
        )

        return job

    def run_resolve_ambiguity_by_ai(
        self,
        job: VideoJob,
        *,
        ambiguity_id: UUID,
    ) -> VideoJob:
        if job.generated_script is None:
            raise RuntimeError("Resolving an ambiguity requires a generated script.")

        matched = next(
            (a for a in job.production_ambiguities if a.id == ambiguity_id), None
        )

        if matched is None:
            raise ValueError(f"No production ambiguity {ambiguity_id} exists.")

        resolved = self.production_ambiguity_service.resolve_by_ai(
            ambiguity=matched, script=job.generated_script
        )

        job.production_ambiguities = [
            resolved if a.id == ambiguity_id else a for a in job.production_ambiguities
        ]

        self.approval_gate_service.record_event(
            job=job,
            stage="production_readiness",
            summary="Production ambiguity resolved by AI.",
            category=DecisionCategory.GENERATION,
        )

        return job

    def compute_script_production_readiness(
        self, job: VideoJob
    ) -> ScriptProductionReadinessReport:
        """
        Content Studio Redesign, Phase 16. Distinct from the
        pre-existing, broader ProductionReadinessService (whole-project
        render/export readiness) - see ScriptProductionReadinessReport's
        docstring.
        """

        return self.script_production_readiness_service.evaluate(job)

    def run_all(self, job: VideoJob) -> VideoJob:
        """
        Run every stage in sequence (Fully Automatic mode), including
        one bounded revision pass if the first quality gate result
        needs revision - not an unbounded improve-until-perfect loop,
        just enough to let a genuinely fixable script self-correct
        once before surfacing to a human.

        Idempotent on re-entry: a stage whose output artifact already
        exists on the job is skipped rather than regenerated, so
        calling run_all() again after a restart (or after resolving an
        approval gate) resumes at the first incomplete stage instead
        of re-spending paid/nondeterministic work redoing what already
        succeeded. run_scene_planning is the one stage checked against
        InvalidationService rather than mere presence, since scenes is
        the only run_all()-produced field that staleness (a script
        revision) can flag without also clearing to None - every other
        field here is reset to None by whatever invalidates it (see
        run_revision), so "already set" and "still valid" coincide for
        them.
        """

        if job.audience_promise is None:
            job = self.run_audience_promise(job)
        if self.approval_gate_service.is_blocked(job, "content_strategy"):
            return job

        if job.research_plan is None:
            job = self.run_research_plan(job)
        if self.approval_gate_service.is_blocked(job, "research_plan"):
            return job

        if job.research is None:
            job = self.run_research(job)
        if self.approval_gate_service.is_blocked(job, "research"):
            return job

        if not job.story_angles:
            job = self.run_story_angles(job)
        if self.approval_gate_service.is_blocked(job, "story_angle"):
            return job

        if job.story_blueprint is None:
            job = self.run_narrative_architecture(job)
        if self.approval_gate_service.is_blocked(job, "narrative_architecture"):
            return job

        if job.retention_audit is None:
            job = self.run_retention_audit(job)
        if not job.hook_candidates:
            job = self.run_hooks(job)
        if self.approval_gate_service.is_blocked(job, "hook"):
            return job

        if job.writing_directives is None:
            job = self.run_writing_directives(job)

        if job.generated_script is None:
            job = self.run_script(job)
        if self.approval_gate_service.is_blocked(job, "final_script"):
            return job

        if job.continuity_bible is None:
            job = self.run_continuity_bible(job)
        if job.editorial_critique is None:
            job = self.run_editorial_critique(job)
        if job.script_quality_report is None:
            job = self.run_quality_gate(job)

        needs_revision = (
            job.script_quality_report is not None
            and job.script_quality_report.status == ScriptQualityStatus.NEEDS_REVISION
            and job.editorial_critique is not None
            and bool(job.editorial_critique.findings)
        )

        if needs_revision:
            job = self.run_revision(job)
            job = self.run_editorial_critique(job)
            job = self.run_quality_gate(job)

        approved = (
            job.script_quality_report is not None
            and job.script_quality_report.status
            == ScriptQualityStatus.APPROVED_FOR_PRODUCTION
        )

        if (
            approved
            and job.script_version_history is not None
            and job.script_lock is None
        ):
            # Content Studio Redesign, Phase 19: route the automatic
            # path through the same run_script_lock() every manual
            # "Approve & lock script" click uses, rather than calling
            # ScriptVersionService.lock_version() directly - a fully
            # automatic run previously ended with the version's
            # locked flag set but no ScriptLock record and no Activity
            # History entry at all, so "the internal content path
            # reaches a valid Script Lock" wasn't actually true end to
            # end. Guarded on job.script_lock is None so a second
            # run_all() call on an already-locked job stays a true
            # no-op, matching this method's own idempotency guarantee.
            #
            # run_script_lock() can refuse (ValueError) over an
            # unresolved continuity-critical ambiguity a caller
            # created via run_production_ambiguity_detection() outside
            # run_all()'s own sequence - run_all() has never raised at
            # this point before, so that case falls back to the
            # pre-Phase-19 behavior (version-level lock flag only)
            # rather than turning a previously-silent completion into
            # a new failure mode.
            history_before_lock = job.script_version_history

            try:
                job = self.run_script_lock(job)
            except ValueError:
                job.script_version_history = self.script_version_service.lock_version(
                    history=history_before_lock,
                    version_number=history_before_lock.current_version.version_number,
                )

        if job.packaging_hypothesis is None:
            job = self.run_packaging_hypothesis(job)

        if not job.scenes or self.invalidation_service.is_stale(job, "scenes"):
            job = self.run_scene_planning(job)

        return job

    def resolve_approval(
        self,
        job: VideoJob,
        decision_point: str,
        action: HumanApprovalAction,
        notes: str | None = None,
    ) -> ApprovalDecision:
        """Apply a human decision to the latest pending gate for one point."""

        return self.approval_gate_service.resolve(
            job=job, decision_point=decision_point, action=action, notes=notes
        )

    def compute_automation_status(self, job: VideoJob) -> AutomationStatus:
        """
        Content Studio Redesign, Phase 17: "Visible current operation
        and completed stages" / "Pause reason and next required user
        action." Pure read of already-persisted state - mirrors
        exactly the presence checks run_all() itself makes, so this
        never drifts from what "Run/Resume Automation" would actually
        do next.
        """

        stage_presence = (
            ("audience_promise", job.audience_promise is not None),
            ("research_plan", job.research_plan is not None),
            ("research", job.research is not None),
            ("story_angles", bool(job.story_angles)),
            ("narrative_architecture", job.story_blueprint is not None),
            ("retention_audit", job.retention_audit is not None),
            ("hooks", bool(job.hook_candidates)),
            ("writing_directives", job.writing_directives is not None),
            ("script", job.generated_script is not None),
            ("continuity_bible", job.continuity_bible is not None),
            ("editorial_critique", job.editorial_critique is not None),
            ("quality_gate", job.script_quality_report is not None),
            ("packaging_hypothesis", job.packaging_hypothesis is not None),
            ("scene_planning", bool(job.scenes)),
        )
        completed_stages = [key for key, present in stage_presence if present]

        pending = ApprovalGateService.latest_pending(job)
        pending_decision_point = (
            pending.approval.decision_point
            if pending is not None and pending.approval is not None
            else None
        )

        return AutomationStatus(
            completed_stages=completed_stages,
            pending_decision_point=pending_decision_point,
            pending_stage=pending.stage if pending is not None else None,
            pending_summary=pending.summary if pending is not None else None,
        )

    def compute_production_handoff_status(
        self, job: VideoJob
    ) -> ProductionHandoffStatus:
        """
        Post-Script-Approval Production Plan, Phase 0: "Emit a post-
        approval production state such as LOCKED / BUILDING_PACKAGE /
        PACKAGE_READY / BLOCKED." Pure read of already-persisted
        state, matching every other compute_*() method's convention.

        BLOCKED: no script lock exists yet - there is nothing for a
            production package to be built from.
        LOCKED: locked, but no scenes have been planned from it yet.
        BUILDING_PACKAGE: locked and scenes exist, but
            InvalidationService already flags them stale (the script
            changed and was re-locked since those scenes were
            planned) - a rebuild is owed, reusing the exact staleness
            mechanism run_all() itself already checks before deciding
            whether to replan scenes, rather than inventing a second
            notion of "out of date."
        PACKAGE_READY: locked, scenes exist, and are not stale.
        """

        if job.script_lock is None:
            return ProductionHandoffStatus(
                state=ProductionHandoffState.BLOCKED,
                blocked_reason="No script lock exists yet - approve and lock the "
                "script before production planning can begin.",
            )

        if not job.scenes:
            return ProductionHandoffStatus(
                state=ProductionHandoffState.LOCKED,
                locked_script_hash=job.script_lock.script_content_hash,
            )

        if self.invalidation_service.is_stale(job, "scenes"):
            return ProductionHandoffStatus(
                state=ProductionHandoffState.BUILDING_PACKAGE,
                locked_script_hash=job.script_lock.script_content_hash,
            )

        return ProductionHandoffStatus(
            state=ProductionHandoffState.PACKAGE_READY,
            locked_script_hash=job.script_lock.script_content_hash,
        )
