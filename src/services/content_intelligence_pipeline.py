from __future__ import annotations

from src.agents.research_agent.agent import ResearchAgent
from src.agents.scene_planner.agent import ScenePlannerAgent
from src.models.approval import ApprovalDecision, HumanApprovalAction
from src.models.editorial_profile import EditorialProfile
from src.models.script_quality_report import ScriptQualityStatus
from src.models.story_blueprint import StoryBeatType
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
from src.services.re_hook_planning_service import ReHookPlanningService
from src.services.research_planning_service import ResearchPlanningService
from src.services.retention_audit_service import RetentionAuditService
from src.services.script_generation_service import ScriptGenerationService
from src.services.script_quality_gate_service import ScriptQualityGateService
from src.services.script_revision_service import ScriptRevisionService
from src.services.script_version_service import ScriptVersionService
from src.services.story_angle_evaluation_service import (
    StoryAngleEvaluationService,
    select_winning_evaluation,
)
from src.services.story_angle_generation_service import StoryAngleGenerationService
from src.services.story_blueprint_generation_service import (
    StoryBlueprintGenerationService,
)


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
        self.script_quality_gate_service = ScriptQualityGateService()
        self.packaging_hypothesis_service = PackagingHypothesisService(
            llm_service=llm_service,
            profile_ids=profile_ids,
            estimated_cost_usd=estimated_cost_usd,
        )
        self.scene_planner = ScenePlannerAgent()
        self.script_version_service = ScriptVersionService()
        self.continuity_bible_extraction_service = ContinuityBibleExtractionService(
            llm_service=llm_service,
            profile_ids=profile_ids,
            estimated_cost_usd=estimated_cost_usd,
        )
        self.continuity_validation_service = ContinuityValidationService()
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

        job.research_plan = self.research_planning_service.plan(
            job.topic, job.audience_promise, editorial_profile
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

    def run_narrative_architecture(self, job: VideoJob) -> VideoJob:
        """Stage 5: plan the reveal map and story blueprint."""

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
        )

        self.approval_gate_service.gate(
            job=job,
            decision_point="narrative_architecture",
            stage="narrative_architecture",
            summary=f"Story blueprint generated with {len(job.story_blueprint.beats)} beats.",
        )

        return job

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

        return job

    def run_hooks(self, job: VideoJob) -> VideoJob:
        """Stage 6: generate/score hooks and plan any scheduled re-hooks."""

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

        return job

    def run_quality_gate(self, job: VideoJob) -> VideoJob:
        """Stage 9: aggregate the critique against genre thresholds."""

        if job.editorial_critique is None:
            raise RuntimeError("The quality gate requires an editorial critique.")

        editorial_profile = job.editorial_profile_snapshot or (
            self.resolve_editorial_profile(job)
        )

        job.script_quality_report = self.script_quality_gate_service.evaluate(
            critique=job.editorial_critique,
            editorial_profile=editorial_profile,
        )

        return job

    def run_revision(self, job: VideoJob) -> VideoJob:
        """
        Stage 10: revise the script to address the current critique's
        findings. The critique and quality report describe the
        pre-revision script, so both are cleared afterward - a fresh
        run_editorial_critique/run_quality_gate pass on the revised
        script is required before it can be approved.
        """

        if job.generated_script is None or job.editorial_critique is None:
            raise RuntimeError(
                "Script revision requires a generated script and an "
                "editorial critique."
            )

        critique = job.editorial_critique

        job.generated_script = self.script_revision_service.revise(
            script=job.generated_script,
            critique=critique,
        )

        if job.script_version_history is not None:
            job.script_version_history = self.script_version_service.add_revision(
                history=job.script_version_history,
                revised_script=job.generated_script,
                critique=critique,
            )

        job.editorial_critique = None
        job.script_quality_report = None

        self.invalidation_service.on_script_changed(job)

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

        self.invalidation_service.clear_stale(job, "scenes")

        return job

    def run_all(self, job: VideoJob) -> VideoJob:
        """
        Run every stage in sequence (Fully Automatic mode), including
        one bounded revision pass if the first quality gate result
        needs revision - not an unbounded improve-until-perfect loop,
        just enough to let a genuinely fixable script self-correct
        once before surfacing to a human.
        """

        job = self.run_audience_promise(job)
        if self.approval_gate_service.is_blocked(job, "content_strategy"):
            return job

        job = self.run_research_plan(job)
        job = self.run_research(job)
        if self.approval_gate_service.is_blocked(job, "research"):
            return job

        job = self.run_story_angles(job)
        if self.approval_gate_service.is_blocked(job, "story_angle"):
            return job

        job = self.run_narrative_architecture(job)
        if self.approval_gate_service.is_blocked(job, "narrative_architecture"):
            return job

        job = self.run_retention_audit(job)
        job = self.run_hooks(job)
        if self.approval_gate_service.is_blocked(job, "hook"):
            return job

        job = self.run_script(job)
        if self.approval_gate_service.is_blocked(job, "final_script"):
            return job

        job = self.run_continuity_bible(job)
        job = self.run_editorial_critique(job)
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

        if approved and job.script_version_history is not None:
            job.script_version_history = self.script_version_service.lock_version(
                history=job.script_version_history,
                version_number=job.script_version_history.current_version.version_number,
            )

        job = self.run_packaging_hypothesis(job)
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
