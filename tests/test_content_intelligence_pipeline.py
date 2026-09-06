from __future__ import annotations

from uuid import uuid4

import pytest

from src.models.approval import ApprovalPolicyConfig
from src.models.production_handoff import ProductionHandoffState
from src.models.script_lock import ScriptProvenance
from src.models.script_selection_edit import (
    SelectionEditOperation,
    SelectionEditRequest,
)
from src.models.script_version import VersionReason
from src.models.video_job import VideoJob
from src.services.approval_gate_service import ApprovalGateService
from src.services.content_intelligence_pipeline import ContentIntelligencePipeline
from src.services.llm.llm_service import LLMServiceResult
from src.shared.llm.models import LLMCallResult, LLMCallStatus, LLMProvider
from src.shared.llm.request import LLMRequest

_CANNED_RESEARCH_SUMMARY = (
    "The Mary Celeste was found adrift and abandoned in 1872, seaworthy "
    "and fully provisioned, with no sign of the crew."
)


class _EchoStubLLMService:
    """
    Returns each request's own dry_run_response - every retrofitted
    content-intelligence service already builds one its own parser
    accepts (the same guarantee each service's own
    test_dry_run_response_is_itself_parseable test proves in
    isolation), so one stub can drive the whole pipeline without
    per-stage canned data.

    ResearchAgent is the one exception: it predates dry_run_response
    and returns real prose researchers are expected to write, so it's
    special-cased here.
    """

    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    def generate(
        self,
        request: LLMRequest,
        *,
        estimated_cost_usd: float = 0.0,
        profile_ids: list[str] | None = None,
    ) -> LLMServiceResult:
        self.requests.append(request)

        if request.dry_run_response is not None:
            content = request.dry_run_response
            if request.metadata.get("agent") == "AudiencePromiseService":
                # The service's own dry-run response deliberately
                # models a MODERATE promise (confidence 0.6), which is
                # correct for exercising that stage in isolation - but
                # it sits below ApprovalService's 0.7 auto-continue
                # threshold, so a run_all() test under full_auto would
                # otherwise (correctly) stop at the very first gate.
                # Swap in STRONG here so full_auto run_all() tests can
                # exercise the whole pipeline end to end.
                content = content.replace(
                    "PROMISE_STRENGTH: moderate", "PROMISE_STRENGTH: strong"
                )
            elif request.metadata.get("agent") == "HookEvaluationService":
                # Same reasoning: the service's own placeholder dry-run
                # scores every dimension (including SPOILER_RISK) at
                # 70, which zeroes out overall_score/confidence_score
                # by construction (raw_average - spoiler_risk = 0).
                # That's fine for testing HookEvaluationService in
                # isolation, but a run_all() test needs a hook that
                # would plausibly auto-continue.
                content = content.replace("SPOILER_RISK: 70", "SPOILER_RISK: 0")
        elif request.metadata.get("agent") == "ResearchAgent":
            content = _CANNED_RESEARCH_SUMMARY
        else:
            content = ""

        result = LLMCallResult(
            status=LLMCallStatus.SUCCESS,
            provider=LLMProvider.OPENAI,
            model="test-model",
            content=content,
        )

        return LLMServiceResult(
            result=result,
            selected_profile_id="test-profile",
            all_providers_failed=False,
        )


def _job(**overrides: object) -> VideoJob:
    base: dict[str, object] = dict(
        project_name="Mary Celeste Documentary",
        channel_name="Maritime Mysteries",
        niche="unsolved maritime disappearances",
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        target_duration_seconds=180,
        target_audience="mystery enthusiasts",
        approval_policy=ApprovalPolicyConfig.full_auto(),
    )
    base.update(overrides)
    # **dict unpacking against a pydantic model's constructor is a
    # known mypy-plugin limitation (this session's own established
    # accepted-debt pattern), and its error count grows by one every
    # time VideoJob gains a new optional field - suppressed here once,
    # robustly, rather than re-litigated on every future field.
    return VideoJob(**base)  # type: ignore[arg-type]


def _pipeline() -> tuple[ContentIntelligencePipeline, _EchoStubLLMService]:
    stub = _EchoStubLLMService()
    pipeline = ContentIntelligencePipeline(llm_service=stub)  # type: ignore[arg-type]
    return pipeline, stub


def test_run_audience_promise_resolves_genre_and_sets_promise() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_audience_promise(_job())

    assert job.editorial_profile_snapshot is not None
    assert job.editorial_profile_snapshot.genre_id == "genre.mystery"
    assert job.audience_promise is not None
    assert job.audience_promise.genre_id == "genre.mystery"


def test_run_research_plan_requires_audience_promise() -> None:
    pipeline, _ = _pipeline()

    with pytest.raises(RuntimeError, match="requires an audience promise"):
        pipeline.run_research_plan(_job())


def test_run_research_plan_produces_questions() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_audience_promise(_job())
    job = pipeline.run_research_plan(job)

    assert job.research_plan is not None
    assert len(job.research_plan.research_questions) > 0


def test_run_research_populates_result() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_research(_job())

    assert job.research is not None
    assert job.research.research_summary == _CANNED_RESEARCH_SUMMARY


def test_run_story_angles_requires_research_and_promise() -> None:
    pipeline, _ = _pipeline()

    with pytest.raises(RuntimeError, match="requires research"):
        pipeline.run_story_angles(_job())


def test_run_story_angles_selects_a_winner() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_audience_promise(_job())
    job = pipeline.run_research(job)
    job = pipeline.run_story_angles(job)

    assert len(job.story_angles) > 0
    assert len(job.story_angle_evaluations) == len(job.story_angles)
    assert job.selected_story_angle is not None
    assert job.selected_story_angle.title in {angle.title for angle in job.story_angles}


def test_run_narrative_architecture_produces_blueprint_and_reveal_map() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_audience_promise(_job())
    job = pipeline.run_research(job)
    job = pipeline.run_story_angles(job)
    job = pipeline.run_narrative_architecture(job)

    assert job.reveal_map is not None
    assert len(job.reveal_map.curiosity_loops) > 0
    assert job.story_blueprint is not None
    assert len(job.story_blueprint.beats) > 0
    assert job.story_blueprint.genre_id == "genre.mystery"


def test_run_narrative_architecture_sets_research_id_and_does_not_mutate_research() -> (
    None
):
    """
    Content Studio Redesign, Phase 9: "Architecture-only regeneration
    must not mutate Research" - job.research is read-only input to
    this stage, before and after, even across a second regeneration.
    """
    pipeline, _ = _pipeline()

    job = pipeline.run_audience_promise(_job())
    job = pipeline.run_research(job)
    job = pipeline.run_story_angles(job)

    research_before = job.research
    assert research_before is not None

    job = pipeline.run_narrative_architecture(job)

    assert job.research is research_before
    assert job.story_blueprint is not None
    assert job.story_blueprint.research_id == research_before.id

    # Regenerate with an instruction - still must not touch research.
    job = pipeline.run_narrative_architecture(
        job, additional_instructions="Compress the slow middle section."
    )

    assert job.research is research_before


def test_bind_curiosity_roles_assigns_the_loop_to_its_containing_beat() -> None:
    from src.models.information_reveal_map import CuriosityLoop, InformationRevealMap
    from src.models.story_blueprint import StoryBeat, StoryBeatType, StoryBlueprint

    blueprint = StoryBlueprint(
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        target_duration_seconds=30,
        beats=[
            StoryBeat(
                beat_type=StoryBeatType.HOOK,
                start_seconds=0,
                end_seconds=10,
                purpose="Open cold.",
                tension_level=60,
            ),
            StoryBeat(
                beat_type=StoryBeatType.CLIMAX,
                start_seconds=10,
                end_seconds=30,
                purpose="Reveal the truth.",
                tension_level=90,
            ),
        ],
        prompt_version="story_blueprint_prompt_v1.0.0",
    )
    reveal_map = InformationRevealMap(
        topic="The Mary Celeste",
        curiosity_loops=[
            CuriosityLoop(
                question="What happened to the crew?",
                opened_at_position=0.1,  # 3s -> first beat
            ),
            CuriosityLoop(
                question="Why was the ship abandoned mid-voyage?",
                opened_at_position=0.6,  # 18s -> second beat
            ),
        ],
        prompt_version="reveal_map_prompt_v1.0.0",
    )

    ContentIntelligencePipeline._bind_curiosity_roles(blueprint, reveal_map)

    hook_beat = blueprint.beats[0]
    climax_beat = blueprint.beats[1]

    assert hook_beat.curiosity_loop_question == "What happened to the crew?"
    assert climax_beat.curiosity_loop_question == (
        "Why was the ship abandoned mid-voyage?"
    )


def test_bind_curiosity_roles_binds_a_loop_opening_at_the_very_end() -> None:
    """
    Regression test (found via external audit): a loop with
    opened_at_position == 1.0 lands exactly on the final beat's
    end_seconds, which the half-open [start, end) check used to
    exclude, leaving it silently unbound.
    """
    from src.models.information_reveal_map import CuriosityLoop, InformationRevealMap
    from src.models.story_blueprint import StoryBeat, StoryBeatType, StoryBlueprint

    blueprint = StoryBlueprint(
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        target_duration_seconds=30,
        beats=[
            StoryBeat(
                beat_type=StoryBeatType.HOOK,
                start_seconds=0,
                end_seconds=20,
                purpose="Open cold.",
                tension_level=60,
            ),
            StoryBeat(
                beat_type=StoryBeatType.PAYOFF,
                start_seconds=20,
                end_seconds=30,
                purpose="Resolve it.",
                tension_level=90,
            ),
        ],
        prompt_version="story_blueprint_prompt_v1.0.0",
    )
    reveal_map = InformationRevealMap(
        topic="The Mary Celeste",
        curiosity_loops=[
            CuriosityLoop(question="What was the final truth?", opened_at_position=1.0),
        ],
        prompt_version="reveal_map_prompt_v1.0.0",
    )

    ContentIntelligencePipeline._bind_curiosity_roles(blueprint, reveal_map)

    assert blueprint.beats[1].curiosity_loop_question == "What was the final truth?"


def test_bind_curiosity_roles_never_overwrites_an_already_assigned_beat() -> None:
    from src.models.information_reveal_map import CuriosityLoop, InformationRevealMap
    from src.models.story_blueprint import StoryBeat, StoryBeatType, StoryBlueprint

    blueprint = StoryBlueprint(
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        target_duration_seconds=10,
        beats=[
            StoryBeat(
                beat_type=StoryBeatType.HOOK,
                start_seconds=0,
                end_seconds=10,
                purpose="Open cold.",
                tension_level=60,
            ),
        ],
        prompt_version="story_blueprint_prompt_v1.0.0",
    )
    reveal_map = InformationRevealMap(
        topic="The Mary Celeste",
        curiosity_loops=[
            CuriosityLoop(question="First question?", opened_at_position=0.1),
            CuriosityLoop(question="Second question?", opened_at_position=0.5),
        ],
        prompt_version="reveal_map_prompt_v1.0.0",
    )

    ContentIntelligencePipeline._bind_curiosity_roles(blueprint, reveal_map)

    # Only the single beat exists, so only the first loop to be
    # processed claims it - the second is left unbound rather than
    # overwriting the first.
    assert blueprint.beats[0].curiosity_loop_question == "First question?"


def test_run_hooks_selects_a_winner() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_audience_promise(_job())
    job = pipeline.run_research(job)
    job = pipeline.run_story_angles(job)
    job = pipeline.run_narrative_architecture(job)
    job = pipeline.run_hooks(job)

    assert len(job.hook_candidates) > 0
    assert len(job.hook_evaluations) == len(job.hook_candidates)
    assert job.selected_hook is not None
    assert job.selected_hook.rejected is False


def test_run_hooks_accepts_additional_instructions() -> None:
    """
    Content Studio Redesign, Phase 10: "Rewrite with Instructions" -
    run_hooks passes additional_instructions straight through to hook
    generation without changing anything else about the stage.
    """
    pipeline, stub = _pipeline()

    job = pipeline.run_audience_promise(_job())
    job = pipeline.run_research(job)
    job = pipeline.run_story_angles(job)
    job = pipeline.run_narrative_architecture(job)
    job = pipeline.run_hooks(job, additional_instructions="Make it more suspenseful.")

    hook_request = next(
        r
        for r in reversed(stub.requests)
        if r.metadata.get("agent") == "HookGenerationService"
    )
    assert "Make it more suspenseful." in hook_request.prompt
    assert job.selected_hook is not None


def test_run_writing_directives_requires_a_selected_hook() -> None:
    pipeline, _ = _pipeline()

    with pytest.raises(RuntimeError, match="require a selected hook"):
        pipeline.run_writing_directives(_job())


def test_run_writing_directives_produces_a_set_including_system_directives() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_audience_promise(_job())
    job = pipeline.run_research(job)
    job = pipeline.run_story_angles(job)
    job = pipeline.run_narrative_architecture(job)
    job = pipeline.run_hooks(job)
    job = pipeline.run_writing_directives(job)

    assert job.writing_directives is not None
    assert len(job.writing_directives.system_directives) == 3


def test_run_all_resolves_writing_directives_before_the_script() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_all(_job())

    assert job.writing_directives is not None
    assert job.generated_script is not None


def test_run_script_requires_upstream_stages() -> None:
    pipeline, _ = _pipeline()

    with pytest.raises(RuntimeError, match="requires a selected hook"):
        pipeline.run_script(_job())


def test_run_retention_audit_requires_blueprint() -> None:
    pipeline, _ = _pipeline()

    with pytest.raises(RuntimeError, match="requires a story blueprint"):
        pipeline.run_retention_audit(_job())


def test_run_retention_audit_produces_a_report() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_audience_promise(_job())
    job = pipeline.run_research(job)
    job = pipeline.run_story_angles(job)
    job = pipeline.run_narrative_architecture(job)
    job = pipeline.run_retention_audit(job)

    assert job.retention_audit is not None
    assert job.retention_audit.genre_id == "genre.mystery"


def test_run_editorial_critique_requires_script_and_research() -> None:
    pipeline, _ = _pipeline()

    with pytest.raises(RuntimeError, match="requires a generated script"):
        pipeline.run_editorial_critique(_job())


def test_run_editorial_critique_scores_dimensions() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_audience_promise(_job())
    job = pipeline.run_research(job)
    job = pipeline.run_story_angles(job)
    job = pipeline.run_narrative_architecture(job)
    job = pipeline.run_hooks(job)
    job = pipeline.run_script(job)
    job = pipeline.run_editorial_critique(job)

    assert job.editorial_critique is not None
    assert len(job.editorial_critique.dimension_scores) > 0


def test_run_quality_gate_requires_critique() -> None:
    pipeline, _ = _pipeline()

    with pytest.raises(RuntimeError, match="requires an editorial critique"):
        pipeline.run_quality_gate(_job())


def test_run_quality_gate_produces_a_status() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_audience_promise(_job())
    job = pipeline.run_research(job)
    job = pipeline.run_story_angles(job)
    job = pipeline.run_narrative_architecture(job)
    job = pipeline.run_hooks(job)
    job = pipeline.run_script(job)
    job = pipeline.run_editorial_critique(job)
    job = pipeline.run_quality_gate(job)

    assert job.script_quality_report is not None
    assert job.script_quality_report.genre_id == "genre.mystery"


def test_run_quality_gate_binds_the_exact_script_version() -> None:
    """Content Studio Redesign, Phase 13: "Quality result binds to
    exact Script version/hash." """

    pipeline, _ = _pipeline()

    job = pipeline.run_audience_promise(_job())
    job = pipeline.run_research(job)
    job = pipeline.run_story_angles(job)
    job = pipeline.run_narrative_architecture(job)
    job = pipeline.run_hooks(job)
    job = pipeline.run_script(job)
    job = pipeline.run_editorial_critique(job)
    job = pipeline.run_quality_gate(job)

    assert job.script_version_history is not None
    assert job.script_quality_report is not None
    assert (
        job.script_quality_report.script_version_number
        == job.script_version_history.current_version.version_number
        == 1
    )
    assert job.script_quality_report.script_content_hash is not None


def test_run_revision_requires_script_and_critique() -> None:
    pipeline, _ = _pipeline()

    with pytest.raises(RuntimeError, match="requires a generated script"):
        pipeline.run_revision(_job())


class _FindingStubLLMService:
    """
    Echoes every stage except EditorialCritiqueService, which returns
    one fixed blocking narrative_coherence finding - shared by every
    test in this file that needs a real, non-empty critique to act on
    (revision, selective fixes, ignore-with-reason).
    """

    def __init__(self) -> None:
        self.echo = _EchoStubLLMService()

    def generate(
        self,
        request: LLMRequest,
        *,
        estimated_cost_usd: float = 0.0,
        profile_ids: list[str] | None = None,
    ) -> LLMServiceResult:
        if request.metadata.get("agent") == "EditorialCritiqueService":
            content = (
                "FACTUAL_CONFIDENCE: 80\n"
                "HOOK_STRENGTH: 80\n"
                "RETENTION_ARCHITECTURE: 80\n"
                "EMOTIONAL_PROGRESSION: 80\n"
                "RESEARCH_GROUNDING: 80\n"
                "NARRATIVE_COHERENCE: 80\n"
                "AUDIENCE_FIT: 80\n"
                "VISUAL_OPPORTUNITY_DENSITY: 80\n"
                "CHARACTER_DEPTH: 80\n"
                "PAYOFF_STRENGTH: 80\n"
                "CONTINUITY: 80\n"
                "---\n"
                "DIMENSION: narrative_coherence\n"
                "SEVERITY: blocking\n"
                "SEGMENT_NUMBER: none\n"
                "PROBLEM: Unsupported claim about the crew's fate.\n"
                "REASON: No source in research backs this claim.\n"
                "RECOMMENDED_CORRECTION: Remove or attribute the claim."
            )

            result = LLMCallResult(
                status=LLMCallStatus.SUCCESS,
                provider=LLMProvider.OPENAI,
                model="test-model",
                content=content,
            )

            return LLMServiceResult(
                result=result,
                selected_profile_id="test-profile",
                all_providers_failed=False,
            )

        return self.echo.generate(
            request,
            estimated_cost_usd=estimated_cost_usd,
            profile_ids=profile_ids,
        )


def _job_with_blocking_finding() -> tuple[ContentIntelligencePipeline, VideoJob]:
    stub = _FindingStubLLMService()
    pipeline = ContentIntelligencePipeline(llm_service=stub)  # type: ignore[arg-type]

    job = pipeline.run_audience_promise(_job())
    job = pipeline.run_research(job)
    job = pipeline.run_story_angles(job)
    job = pipeline.run_narrative_architecture(job)
    job = pipeline.run_hooks(job)
    job = pipeline.run_script(job)
    job = pipeline.run_editorial_critique(job)
    job = pipeline.run_quality_gate(job)

    return pipeline, job


def test_run_revision_clears_the_stale_critique_and_quality_report() -> None:
    pipeline, job = _job_with_blocking_finding()

    assert job.script_quality_report is not None
    assert job.script_quality_report.status.value == "needs_revision"

    job = pipeline.run_revision(job)

    assert job.editorial_critique is None
    assert job.script_quality_report is None
    assert job.generated_script is not None

    # The blocking finding above scored narrative_coherence - a
    # narrative-dimension finding - so the new version should be
    # classified NARRATIVE, appended as version 2 with version 1 as
    # its parent.
    assert job.script_version_history is not None
    assert job.script_version_history.current_version.version_number == 2
    assert job.script_version_history.current_version.parent_version_number == 1
    assert job.script_version_history.current_version.change_class.value == "narrative"


def test_run_revision_with_finding_ids_only_addresses_the_selected_findings() -> None:
    """Content Studio Redesign, Phase 13: "Apply Selected Fixes"."""

    pipeline, job = _job_with_blocking_finding()
    assert job.editorial_critique is not None
    finding_id = job.editorial_critique.findings[0].id

    job = pipeline.run_revision(job, finding_ids=[finding_id])

    assert job.editorial_critique is None
    assert job.script_quality_report is None
    assert job.script_version_history is not None
    assert job.script_version_history.current_version.version_number == 2


def test_run_ignore_finding_records_a_resolution_without_changing_the_script() -> None:
    """Content Studio Redesign, Phase 13: "Store ignored findings with
    user reason" - ignoring never mutates the script itself."""

    pipeline, job = _job_with_blocking_finding()
    assert job.script_quality_report is not None
    finding_id = job.script_quality_report.blocking_findings[0].id
    original_narration = job.generated_script.full_narration  # type: ignore[union-attr]

    job = pipeline.run_ignore_finding(
        job, finding_id=finding_id, reason="Confirmed acceptable for this project."
    )

    assert job.script_quality_report is not None
    resolution = job.script_quality_report.resolution_for(finding_id)
    assert resolution is not None
    assert resolution.reason == "Confirmed acceptable for this project."
    assert job.script_quality_report.unresolved_blocking_findings == []
    assert job.generated_script.full_narration == original_narration  # type: ignore[union-attr]


def test_run_ignore_finding_requires_an_existing_quality_report() -> None:
    pipeline, _ = _pipeline()

    with pytest.raises(RuntimeError, match="no quality report"):
        pipeline.run_ignore_finding(
            _job(), finding_id=uuid4(), reason="Doesn't matter."
        )


def test_run_script_selection_edit_invalidates_a_stale_quality_report() -> None:
    """
    Content Studio Redesign, Phase 13: "Quality result invalidation
    after script change" applies to every script-mutating path, not
    only the critique-driven run_revision.
    """

    pipeline, job = _job_with_blocking_finding()
    assert job.script_quality_report is not None
    target_segment = job.generated_script.segments[0].segment_number  # type: ignore[union-attr]

    job = pipeline.run_script_selection_edit(
        job,
        request=SelectionEditRequest(
            segment_number=target_segment, operation=SelectionEditOperation.REWRITE
        ),
    )

    assert job.editorial_critique is None
    assert job.script_quality_report is None


def test_run_script_restore_invalidates_a_stale_quality_report() -> None:
    pipeline, job = _job_with_blocking_finding()
    assert job.script_quality_report is not None

    job = pipeline.run_script_restore(job, version_number=1)

    assert job.editorial_critique is None
    assert job.script_quality_report is None


def _job_with_script() -> tuple[ContentIntelligencePipeline, VideoJob]:
    pipeline, _ = _pipeline()

    job = pipeline.run_audience_promise(_job())
    job = pipeline.run_research(job)
    job = pipeline.run_story_angles(job)
    job = pipeline.run_narrative_architecture(job)
    job = pipeline.run_hooks(job)
    job = pipeline.run_script(job)

    return pipeline, job


def test_run_script_selection_edit_requires_a_generated_script() -> None:
    pipeline, _ = _pipeline()

    with pytest.raises(RuntimeError, match="requires a generated script"):
        pipeline.run_script_selection_edit(
            _job(),
            request=SelectionEditRequest(
                segment_number=1, operation=SelectionEditOperation.REWRITE
            ),
        )


def test_run_script_selection_edit_appends_a_manual_edit_version() -> None:
    pipeline, job = _job_with_script()
    assert job.generated_script is not None
    target_segment = job.generated_script.segments[0].segment_number

    job = pipeline.run_script_selection_edit(
        job,
        request=SelectionEditRequest(
            segment_number=target_segment, operation=SelectionEditOperation.REWRITE
        ),
    )

    assert job.script_version_history is not None
    assert job.script_version_history.current_version.version_number == 2
    assert (
        job.script_version_history.current_version.reason == VersionReason.MANUAL_EDIT
    )


def test_run_script_selection_edit_raises_when_current_version_is_locked() -> None:
    pipeline, job = _job_with_script()
    assert job.script_version_history is not None

    job.script_version_history = pipeline.script_version_service.lock_version(
        history=job.script_version_history, version_number=1
    )

    with pytest.raises(RuntimeError, match="is locked"):
        pipeline.run_script_selection_edit(
            job,
            request=SelectionEditRequest(
                segment_number=1, operation=SelectionEditOperation.REWRITE
            ),
        )


def test_run_script_restore_requires_version_history() -> None:
    pipeline, _ = _pipeline()

    with pytest.raises(RuntimeError, match="no script version history"):
        pipeline.run_script_restore(_job(), version_number=1)


def test_run_script_restore_creates_a_new_version_with_the_old_content() -> None:
    pipeline, job = _job_with_script()
    original_narration = job.generated_script.full_narration  # type: ignore[union-attr]

    job = pipeline.run_script_selection_edit(
        job,
        request=SelectionEditRequest(
            segment_number=job.generated_script.segments[0].segment_number,  # type: ignore[union-attr]
            operation=SelectionEditOperation.REWRITE,
        ),
    )

    assert job.generated_script.full_narration != original_narration  # type: ignore[union-attr]

    job = pipeline.run_script_restore(job, version_number=1)

    assert job.generated_script is not None
    assert job.generated_script.full_narration == original_narration
    assert job.script_version_history is not None
    assert job.script_version_history.current_version.version_number == 3
    assert job.script_version_history.current_version.reason == VersionReason.RESTORE
    assert job.script_version_history.current_version.restored_from_version_number == 1


def test_run_script_lock_produces_a_lock_bound_to_the_current_version() -> None:
    pipeline, job = _job_with_script()

    job = pipeline.run_script_lock(job)

    assert job.script_lock is not None
    assert job.script_lock.script_version_number == 1
    assert job.script_lock.script_content_hash == job.generated_script.content_hash  # type: ignore[union-attr]
    assert job.script_lock.provenance == ScriptProvenance.INTERNAL
    assert job.script_version_history is not None
    assert job.script_version_history.is_locked is True


def test_run_script_lock_raises_with_unresolved_blocking_findings() -> None:
    pipeline, job = _job_with_blocking_finding()

    with pytest.raises(ValueError, match="unresolved blocking"):
        pipeline.run_script_lock(job)

    assert job.script_lock is None


def test_run_script_lock_with_override_reason_succeeds() -> None:
    pipeline, job = _job_with_blocking_finding()

    job = pipeline.run_script_lock(job, override_reason="Approved despite finding.")

    assert job.script_lock is not None
    assert job.script_lock.override_reason == "Approved despite finding."


def test_run_revision_raises_and_does_not_mutate_a_locked_script() -> None:
    """
    Content Studio Redesign, Phase 14: "Cannot silently edit locked
    script" - this is the specific bug the phase's own test
    requirement was written to catch: run_revision() used to mutate
    job.generated_script before checking the lock.
    """

    pipeline, job = _job_with_blocking_finding()
    job = pipeline.run_script_lock(job, override_reason="Approved despite finding.")
    original_narration = job.generated_script.full_narration  # type: ignore[union-attr]

    # A fresh critique is required to even attempt run_revision - the
    # lock check must fire before any LLM call or mutation happens.
    from src.models.editorial_critique import (
        CriticFinding,
        EditorialCritique,
        FindingSeverity,
        QualityDimension,
    )

    job.editorial_critique = EditorialCritique(
        topic=job.topic,
        dimension_scores={},
        findings=[
            CriticFinding(
                dimension=QualityDimension.NARRATIVE_COHERENCE,
                severity=FindingSeverity.MINOR,
                segment_number=None,
                problem="Minor wording issue.",
                reason="Reads slightly awkward.",
                recommended_correction="Rephrase for flow.",
            )
        ],
        prompt_version="editorial_critique_prompt_v1.0.0",
    )

    with pytest.raises(RuntimeError, match="is locked"):
        pipeline.run_revision(job)

    assert job.generated_script.full_narration == original_narration  # type: ignore[union-attr]


def test_run_script_unlock_clears_the_lock_and_the_version_flag() -> None:
    pipeline, job = _job_with_script()
    job = pipeline.run_script_lock(job)

    job = pipeline.run_script_unlock(job)

    assert job.script_lock is None
    assert job.script_version_history is not None
    assert job.script_version_history.is_locked is False


def test_run_script_unlock_raises_when_not_locked() -> None:
    pipeline, job = _job_with_script()

    with pytest.raises(RuntimeError, match="not locked"):
        pipeline.run_script_unlock(job)


def test_compute_script_unlock_impact_reflects_real_downstream_fields() -> None:
    pipeline, job = _job_with_script()

    assert pipeline.compute_script_unlock_impact(job) == []

    job = pipeline.run_script_lock(job)
    job = pipeline.run_scene_planning(job)

    assert "scenes" in pipeline.compute_script_unlock_impact(job)


def test_run_script_intake_creates_a_script_and_version_history() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_script_intake(
        _job(target_duration_seconds=2), raw_text="Imported narration text."
    )

    assert job.generated_script is not None
    assert job.generated_script.full_narration == "Imported narration text."
    assert job.script_version_history is not None
    assert job.script_version_history.current_version.version_number == 1
    assert job.script_intake_result is not None


def test_run_script_intake_builds_no_fake_upstream_artifacts() -> None:
    """
    Content Studio Redesign, Phase 15 exit criterion: "No fake
    Research/Hook/Beat artifacts are generated merely to satisfy
    dependencies."
    """

    pipeline, _ = _pipeline()

    job = pipeline.run_script_intake(
        _job(target_duration_seconds=2), raw_text="Imported narration text."
    )

    assert job.research is None
    assert job.selected_hook is None
    assert job.story_blueprint is None
    assert job.selected_story_angle is None


def test_run_script_intake_trust_my_script_skips_analysis() -> None:
    from src.models.script_intake import ScriptIntakeMode

    pipeline, stub = _pipeline()

    # A target duration matching the narration's own estimated length
    # keeps this test focused on "no analysis call happened" without
    # also tripping the separately-tested duration-mismatch check.
    job = pipeline.run_script_intake(
        _job(target_duration_seconds=1),
        raw_text="Imported narration text.",
        mode=ScriptIntakeMode.TRUST_MY_SCRIPT,
    )

    assert job.script_intake_result is not None
    assert job.script_intake_result.mismatches == []
    assert not any(
        request.metadata.get("agent") == "ScriptIntakeService"
        for request in stub.requests
    )


def test_run_script_intake_raises_when_current_version_is_locked() -> None:
    pipeline, job = _job_with_script()
    job = pipeline.run_script_lock(job)

    with pytest.raises(RuntimeError, match="is locked"):
        pipeline.run_script_intake(job, raw_text="A replacement script.")


def test_run_script_lock_defaults_to_external_provenance_after_intake() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_script_intake(
        _job(target_duration_seconds=2), raw_text="Imported narration text."
    )
    job = pipeline.run_script_lock(job)

    assert job.script_lock is not None
    assert job.script_lock.provenance == ScriptProvenance.EXTERNAL


def test_run_script_lock_stays_internal_for_a_generated_script() -> None:
    pipeline, job = _job_with_script()

    job = pipeline.run_script_lock(job)

    assert job.script_lock is not None
    assert job.script_lock.provenance == ScriptProvenance.INTERNAL


def test_run_production_ambiguity_detection_requires_a_script() -> None:
    pipeline, _ = _pipeline()

    with pytest.raises(RuntimeError, match="requires a generated script"):
        pipeline.run_production_ambiguity_detection(_job())


def test_run_production_ambiguity_detection_appends_to_the_job() -> None:
    pipeline, job = _job_with_script()

    job = pipeline.run_production_ambiguity_detection(job)

    assert len(job.production_ambiguities) >= 1

    # Running it again appends rather than replacing.
    job = pipeline.run_production_ambiguity_detection(job)
    assert len(job.production_ambiguities) >= 2


def test_run_resolve_ambiguity_manually_updates_the_matching_entry() -> None:
    pipeline, job = _job_with_script()
    job = pipeline.run_production_ambiguity_detection(job)
    target_id = job.production_ambiguities[0].id

    job = pipeline.run_resolve_ambiguity_manually(
        job, ambiguity_id=target_id, note="Confirmed by the editor."
    )

    resolved = next(a for a in job.production_ambiguities if a.id == target_id)
    assert resolved.status.value == "resolved_manually"
    assert resolved.resolution_note == "Confirmed by the editor."


def test_run_resolve_ambiguity_by_ai_updates_the_matching_entry() -> None:
    pipeline, job = _job_with_script()
    job = pipeline.run_production_ambiguity_detection(job)
    target_id = job.production_ambiguities[0].id

    job = pipeline.run_resolve_ambiguity_by_ai(job, ambiguity_id=target_id)

    resolved = next(a for a in job.production_ambiguities if a.id == target_id)
    assert resolved.status.value == "resolved_by_ai"
    assert resolved.resolution_note is not None


def test_run_resolve_ambiguity_by_ai_raises_for_an_unknown_id() -> None:
    pipeline, job = _job_with_script()

    with pytest.raises(ValueError, match="No production ambiguity"):
        pipeline.run_resolve_ambiguity_by_ai(job, ambiguity_id=uuid4())


def test_compute_script_production_readiness_reflects_real_job_state() -> None:
    pipeline, job = _job_with_script()

    not_ready = pipeline.compute_script_production_readiness(job)
    assert not_ready.is_ready is False

    job = pipeline.run_continuity_bible(job)
    job = pipeline.run_scene_planning(job)

    ready = pipeline.compute_script_production_readiness(job)
    assert ready.has_continuity_bible is True
    assert ready.has_scenes is True
    assert ready.is_ready is True


def test_run_script_lock_raises_with_unresolved_continuity_critical_ambiguity() -> None:
    from src.models.production_ambiguity import (
        AmbiguityResolutionStatus,
        ProductionAmbiguity,
    )

    pipeline, job = _job_with_script()
    job.production_ambiguities = [
        ProductionAmbiguity(description="Unclear identity.", continuity_critical=True)
    ]

    with pytest.raises(ValueError, match="unresolved continuity-critical"):
        pipeline.run_script_lock(job)

    job.production_ambiguities[0] = job.production_ambiguities[0].model_copy(
        update={
            "status": AmbiguityResolutionStatus.RESOLVED_MANUALLY,
            "resolution_note": "Confirmed.",
        }
    )
    job = pipeline.run_script_lock(job)
    assert job.script_lock is not None


def test_compute_automation_status_reflects_no_progress_on_a_fresh_job() -> None:
    pipeline, _ = _pipeline()

    status = pipeline.compute_automation_status(_job())

    assert status.completed_stages == []
    assert status.is_paused is False
    assert status.is_complete is False


def test_compute_automation_status_lists_completed_stages() -> None:
    pipeline, job = _job_with_script()

    status = pipeline.compute_automation_status(job)

    assert "audience_promise" in status.completed_stages
    assert "research" in status.completed_stages
    assert "script" in status.completed_stages
    assert "scene_planning" not in status.completed_stages


def test_compute_automation_status_reports_the_pending_gate() -> None:
    """
    Content Studio Redesign, Phase 17: "Pause reason and next required
    user action" - reuses ApprovalGateService.latest_pending(), the
    same mechanism run_all() itself checks via is_blocked().
    """

    pipeline, _ = _pipeline()
    job = _job(approval_policy=ApprovalPolicyConfig.review_critical_stages())

    job = pipeline.run_all(job)
    status = pipeline.compute_automation_status(job)

    assert status.is_paused is True
    assert status.pending_decision_point is not None


def test_compute_automation_status_is_complete_once_run_all_finishes() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_all(_job())
    status = pipeline.compute_automation_status(job)

    assert status.is_complete is True
    assert status.is_paused is False


def test_run_all_custom_gate_matrix_full_auto_completes_without_pausing() -> None:
    """
    Content Studio Redesign, Phase 17 exit criterion: "All workflow
    modes are configuration of one engine, not three separate
    implementations" - FULL_AUTO/REVIEW_CRITICAL_STAGES/MANUAL_EDITORIAL
    are all just ApprovalPolicyConfig presets consumed by this same
    run_all(), never three different code paths.
    """

    pipeline, _ = _pipeline()

    job = pipeline.run_all(_job(approval_policy=ApprovalPolicyConfig.full_auto()))

    assert job.generated_script is not None
    assert job.scenes


def test_run_all_custom_gate_matrix_manual_editorial_pauses_early() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_all(
        _job(approval_policy=ApprovalPolicyConfig.manual_editorial())
    )

    assert ApprovalGateService.latest_pending(job) is not None


def test_run_packaging_hypothesis_requires_script_and_hook() -> None:
    pipeline, _ = _pipeline()

    with pytest.raises(RuntimeError, match="requires a generated script"):
        pipeline.run_packaging_hypothesis(_job())


def test_run_packaging_hypothesis_produces_title_territories() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_audience_promise(_job())
    job = pipeline.run_research(job)
    job = pipeline.run_story_angles(job)
    job = pipeline.run_narrative_architecture(job)
    job = pipeline.run_hooks(job)
    job = pipeline.run_script(job)
    job = pipeline.run_packaging_hypothesis(job)

    assert job.packaging_hypothesis is not None
    assert len(job.packaging_hypothesis.title_territories) > 0
    assert job.packaging_hypothesis.genre_id == "genre.mystery"


def test_run_script_starts_a_version_history() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_audience_promise(_job())
    job = pipeline.run_research(job)
    job = pipeline.run_story_angles(job)
    job = pipeline.run_narrative_architecture(job)
    job = pipeline.run_hooks(job)
    job = pipeline.run_script(job)

    assert job.script_version_history is not None
    assert job.script_version_history.current_version.version_number == 1
    assert job.script_version_history.current_version.change_class is None


def test_run_all_locks_the_approved_version() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_all(_job())

    assert job.script_version_history is not None
    assert job.script_quality_report is not None
    assert job.script_quality_report.status.value == "approved_for_production"
    assert job.script_version_history.is_locked is True

    # Content Studio Redesign, Phase 19: "the internal content path
    # reaches a valid Script Lock" - not just the version's boolean
    # locked flag, the real Phase 14 ScriptLock record with an
    # Activity History entry to match.
    assert job.script_lock is not None
    assert job.script_lock.provenance == ScriptProvenance.INTERNAL
    lock_records = [
        record for record in job.content_decisions if record.category == "lock"
    ]
    assert len(lock_records) == 1

    # Idempotent: calling run_all() again on an already-locked,
    # already-complete job must not build a second ScriptLock or
    # append a second lock record.
    first_lock_id = job.script_lock.id
    job = pipeline.run_all(job)

    assert job.script_lock is not None
    assert job.script_lock.id == first_lock_id
    lock_records_after = [
        record for record in job.content_decisions if record.category == "lock"
    ]
    assert len(lock_records_after) == 1


def test_run_all_reaches_a_script_lock_for_an_intake_originated_script() -> None:
    """
    Content Studio Redesign, Phase 19: the "Import Approved Script"
    (external) path must also reach a valid Script Lock, with
    EXTERNAL provenance inferred automatically - proving the two
    named E2E flows (internal content production, external approved
    script) both terminate the same way rather than needing separate
    lock logic.
    """

    pipeline, _ = _pipeline()

    job = pipeline.run_script_intake(_job(), raw_text="Imported narration text.")
    job = pipeline.run_script_lock(job)

    assert job.script_lock is not None
    assert job.script_lock.provenance == ScriptProvenance.EXTERNAL
    assert job.script_version_history is not None
    assert job.script_version_history.is_locked is True


def test_compute_production_handoff_status_is_blocked_without_a_lock() -> None:
    pipeline, _ = _pipeline()

    status = pipeline.compute_production_handoff_status(_job())

    assert status.state == ProductionHandoffState.BLOCKED
    assert status.blocked_reason is not None


def test_compute_production_handoff_status_is_locked_before_scenes_exist() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_script_intake(_job(), raw_text="Imported narration text.")
    job = pipeline.run_script_lock(job)

    status = pipeline.compute_production_handoff_status(job)

    assert status.state == ProductionHandoffState.LOCKED
    assert status.locked_script_hash == job.script_lock.script_content_hash


def test_compute_production_handoff_status_is_package_ready_once_scenes_exist() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_all(_job())

    assert job.script_lock is not None
    status = pipeline.compute_production_handoff_status(job)

    assert status.state == ProductionHandoffState.PACKAGE_READY
    assert status.is_ready is True


def test_scenes_are_stamped_with_the_locked_script_hash() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_all(_job())

    assert job.script_lock is not None
    assert job.scenes
    assert all(
        scene.locked_script_hash == job.script_lock.script_content_hash
        for scene in job.scenes
    )


def test_compute_production_handoff_status_is_building_package_when_scenes_are_stale() -> (
    None
):
    pipeline, _ = _pipeline()

    job = pipeline.run_all(_job())
    assert job.script_lock is not None

    # Simulate a downstream re-lock (e.g. after unlock+re-edit+re-lock)
    # leaving the existing scenes flagged stale, without re-running
    # scene planning yet.
    pipeline.invalidation_service.on_script_changed(job)

    status = pipeline.compute_production_handoff_status(job)

    assert status.state == ProductionHandoffState.BUILDING_PACKAGE


def test_run_production_semantic_brief_requires_a_script_lock() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_audience_promise(_job())
    job = pipeline.run_research(job)
    job = pipeline.run_story_angles(job)
    job = pipeline.run_narrative_architecture(job)
    job = pipeline.run_hooks(job)
    job = pipeline.run_script(job)

    with pytest.raises(RuntimeError, match="requires a locked script"):
        pipeline.run_production_semantic_brief(job)


def test_run_production_semantic_brief_covers_the_full_locked_script() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_all(_job())
    assert job.script_lock is not None

    job = pipeline.run_production_semantic_brief(job)

    assert job.production_semantic_brief is not None
    assert job.production_semantic_brief.script_lock_hash == (
        job.script_lock.script_content_hash
    )
    assert len(job.production_semantic_brief.segments) == len(
        job.generated_script.segments
    )


def test_run_production_semantic_brief_records_a_generation_event() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_all(_job())
    job = pipeline.run_production_semantic_brief(job)

    matching = [
        record
        for record in job.content_decisions
        if record.stage == "production_semantic_brief"
    ]
    assert len(matching) == 1
    assert matching[0].category == "generation"


def test_run_visual_continuity_requires_a_script_lock() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_audience_promise(_job())
    job = pipeline.run_research(job)
    job = pipeline.run_story_angles(job)
    job = pipeline.run_narrative_architecture(job)
    job = pipeline.run_hooks(job)
    job = pipeline.run_script(job)
    job = pipeline.run_continuity_bible(job)
    job = pipeline.run_scene_planning(job)

    with pytest.raises(RuntimeError, match="requires a locked script"):
        pipeline.run_visual_continuity(job)


def test_run_visual_continuity_requires_scenes() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_all(_job())
    job.scenes = []

    with pytest.raises(RuntimeError, match="requires planned scenes"):
        pipeline.run_visual_continuity(job)


def test_run_visual_continuity_requires_a_continuity_bible() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_all(_job())
    job.continuity_bible = None

    with pytest.raises(RuntimeError, match="requires a continuity bible"):
        pipeline.run_visual_continuity(job)


def test_run_visual_continuity_builds_a_bible_bound_to_the_lock() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_all(_job())
    job = pipeline.run_visual_continuity(job)

    assert job.visual_continuity_bible is not None
    assert job.visual_continuity_bible.script_lock_hash == (
        job.script_lock.script_content_hash
    )
    assert len(job.visual_continuity_bible.clip_entries) == len(job.scenes)


def test_run_visual_continuity_records_a_generation_event() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_all(_job())
    job = pipeline.run_visual_continuity(job)

    matching = [
        record
        for record in job.content_decisions
        if record.stage == "visual_continuity"
    ]
    assert len(matching) == 1
    assert matching[0].category == "generation"


def test_compute_visual_continuity_validation_is_none_before_generation() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_all(_job())

    assert pipeline.compute_visual_continuity_validation(job) is None


def test_compute_visual_continuity_validation_after_generation() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_all(_job())
    job = pipeline.run_visual_continuity(job)

    result = pipeline.compute_visual_continuity_validation(job)

    assert result is not None
    assert result.script_lock_hash == job.script_lock.script_content_hash


def test_run_shot_planning_requires_visual_continuity() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_all(_job())

    with pytest.raises(RuntimeError, match="requires a visual continuity bible"):
        pipeline.run_shot_planning(job)


def test_run_shot_planning_requires_a_script_lock() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_audience_promise(_job())
    job = pipeline.run_research(job)
    job = pipeline.run_story_angles(job)
    job = pipeline.run_narrative_architecture(job)
    job = pipeline.run_hooks(job)
    job = pipeline.run_script(job)
    job = pipeline.run_continuity_bible(job)
    job = pipeline.run_scene_planning(job)

    with pytest.raises(RuntimeError, match="requires a locked script"):
        pipeline.run_shot_planning(job)


def test_run_shot_planning_builds_a_plan_with_one_shot_per_scene() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_all(_job())
    job = pipeline.run_visual_continuity(job)
    job = pipeline.run_shot_planning(job)

    assert job.cinematic_shot_plan is not None
    assert job.cinematic_shot_plan.has_exactly_one_shot_per_scene is True
    assert job.cinematic_shot_plan.script_lock_hash == (
        job.script_lock.script_content_hash
    )


def test_run_shot_planning_records_a_generation_event() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_all(_job())
    job = pipeline.run_visual_continuity(job)
    job = pipeline.run_shot_planning(job)

    matching = [
        record for record in job.content_decisions if record.stage == "shot_planning"
    ]
    assert len(matching) == 1
    assert matching[0].category == "generation"


def test_run_cinematic_prompt_compilation_requires_shot_plan() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_all(_job())
    job = pipeline.run_visual_continuity(job)

    with pytest.raises(RuntimeError, match="requires a cinematic shot plan"):
        pipeline.run_cinematic_prompt_compilation(job)


def test_run_cinematic_prompt_compilation_produces_one_prompt_per_scene() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_all(_job())
    job = pipeline.run_visual_continuity(job)
    job = pipeline.run_shot_planning(job)
    job = pipeline.run_cinematic_prompt_compilation(job)

    assert job.cinematic_prompt_package is not None
    assert len(job.cinematic_prompt_package.prompts) == len(job.scenes)
    assert job.cinematic_prompt_package.script_lock_hash == (
        job.script_lock.script_content_hash
    )


def test_run_cinematic_prompt_quality_requires_a_compiled_package() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_all(_job())

    with pytest.raises(RuntimeError, match="requires a compiled"):
        pipeline.run_cinematic_prompt_quality(job)


def test_run_cinematic_prompt_quality_scores_the_package() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_all(_job())
    job = pipeline.run_visual_continuity(job)
    job = pipeline.run_shot_planning(job)
    job = pipeline.run_cinematic_prompt_compilation(job)
    job = pipeline.run_cinematic_prompt_quality(job)

    assert job.cinematic_prompt_package is not None
    scored = [p for p in job.cinematic_prompt_package.prompts if p.is_scored]
    assert len(scored) >= 1


def test_compute_clip_materialization_status_reflects_scenes() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_all(_job())

    status = pipeline.compute_clip_materialization_status(job)

    assert status.total_clips == len(job.scenes)
    assert status.planned_duration_seconds == sum(
        scene.estimated_duration_seconds for scene in job.scenes
    )


def test_compute_clip_materialization_status_tracks_prompt_tracing() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_all(_job())
    job = pipeline.run_visual_continuity(job)
    job = pipeline.run_shot_planning(job)
    job = pipeline.run_cinematic_prompt_compilation(job)

    status = pipeline.compute_clip_materialization_status(job)

    assert status.traced_to_prompt_clips == len(job.scenes)
    assert status.is_fully_traced is True


def test_run_continuity_bible_requires_a_generated_script() -> None:
    pipeline, _ = _pipeline()

    with pytest.raises(RuntimeError, match="requires a generated script"):
        pipeline.run_continuity_bible(_job())


def test_run_continuity_bible_extracts_and_validates() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_audience_promise(_job())
    job = pipeline.run_research(job)
    job = pipeline.run_story_angles(job)
    job = pipeline.run_narrative_architecture(job)
    job = pipeline.run_hooks(job)
    job = pipeline.run_script(job)
    job = pipeline.run_continuity_bible(job)

    assert job.continuity_bible is not None
    assert job.continuity_validation is not None


def test_run_scene_planning_requires_a_generated_script() -> None:
    pipeline, _ = _pipeline()

    with pytest.raises(RuntimeError, match="requires a generated script"):
        pipeline.run_scene_planning(_job())


def test_run_scene_planning_produces_genre_aware_scenes() -> None:
    pipeline, _ = _pipeline()

    job = pipeline.run_audience_promise(_job())
    job = pipeline.run_research(job)
    job = pipeline.run_story_angles(job)
    job = pipeline.run_narrative_architecture(job)
    job = pipeline.run_hooks(job)
    job = pipeline.run_script(job)
    job = pipeline.run_scene_planning(job)

    assert len(job.scenes) > 0
    assert all(scene.narrative_function is not None for scene in job.scenes)


def test_run_all_produces_a_complete_and_quality_gated_script() -> None:
    pipeline, stub = _pipeline()

    job = pipeline.run_all(_job())

    assert job.audience_promise is not None
    assert job.research is not None
    assert job.selected_story_angle is not None
    assert job.story_blueprint is not None
    assert job.retention_audit is not None
    assert job.selected_hook is not None
    assert job.generated_script is not None
    assert len(job.generated_script.segments) == len(job.story_blueprint.beats)
    assert job.generated_script.genre_id == "genre.mystery"
    assert job.continuity_bible is not None
    assert job.continuity_validation is not None
    assert job.editorial_critique is not None
    assert job.script_quality_report is not None
    assert job.packaging_hypothesis is not None
    assert len(job.scenes) > 0

    # Every stage's genre-specific prompt content actually reached the
    # LLM - confirms the pipeline threads editorial_profile through,
    # not just that each service works in isolation.
    combined_prompts = "\n".join(
        (request.prompt or "") + (request.system_prompt or "")
        for request in stub.requests
    )
    assert "genre.mystery" in combined_prompts


def test_resolve_editorial_profile_raises_for_unknown_genre_without_fallback() -> None:
    pipeline, _ = _pipeline()
    pipeline.genre_registry = pipeline.genre_registry.__class__()  # empty registry

    with pytest.raises(RuntimeError, match="Could not resolve"):
        pipeline.resolve_editorial_profile(_job())


def test_run_all_stops_at_the_first_review_gated_stage() -> None:
    pipeline, _ = _pipeline()
    job = _job(approval_policy=ApprovalPolicyConfig.review_critical_stages())

    job = pipeline.run_all(job)

    # review_critical_stages() gates story_angle/narrative_architecture/
    # final_script, not content_strategy/research - so run_all should
    # complete research and stop right after story angle selection.
    assert job.audience_promise is not None
    assert job.research is not None
    assert job.selected_story_angle is not None
    assert job.story_blueprint is None
    assert job.generated_script is None

    from src.services.approval_gate_service import ApprovalGateService

    pending = ApprovalGateService.latest_pending(job)
    assert pending is not None
    assert pending.approval is not None
    assert pending.approval.decision_point == "story_angle"


def test_resolving_a_pending_decision_unblocks_the_next_manual_stage() -> None:
    from src.models.approval import HumanApprovalAction
    from src.services.approval_gate_service import ApprovalGateService

    pipeline, _ = _pipeline()
    job = _job(approval_policy=ApprovalPolicyConfig.review_critical_stages())

    job = pipeline.run_all(job)
    assert ApprovalGateService.is_blocked(job, "story_angle") is True

    pipeline.resolve_approval(job, "story_angle", HumanApprovalAction.APPROVE)
    assert ApprovalGateService.is_blocked(job, "story_angle") is False

    # run_all() is idempotent on re-entry (Phase A1): it skips every
    # stage whose output already exists, so calling it again after
    # resolving the gate resumes from exactly where it left off rather
    # than restarting from stage one - this is the real fix for what
    # used to be documented as a deferred limitation.
    job = pipeline.run_all(job)

    assert job.story_blueprint is not None


def test_research_plan_auto_approves_and_does_not_block_research() -> None:
    """
    Content Studio Redesign, Phase 7: research_plan defaults to AUTO
    (like topic/research/hook) - confidence=None resolves immediately
    to APPROVED, so a plain full_auto()/review_critical_stages()
    project's run_all() reaches research unchanged from before this
    phase (see the module's own test_run_all_stops_at_the_first_
    review_gated_stage, which already asserts job.research is not
    None under review_critical_stages()).
    """
    from src.services.approval_gate_service import ApprovalGateService

    pipeline, _ = _pipeline()
    job = pipeline.run_research_plan(pipeline.run_audience_promise(_job()))

    assert ApprovalGateService.is_blocked(job, "research_plan") is False

    research_plan_records = [
        record
        for record in job.content_decisions
        if record.approval is not None
        and record.approval.decision_point == "research_plan"
    ]
    assert len(research_plan_records) == 1
    assert research_plan_records[0].approval is not None
    assert research_plan_records[0].approval.state.value == "approved"


def test_run_all_stops_before_research_when_research_plan_requires_review() -> None:
    """
    "No retrieval job starts until brief approval/start action" -
    setting research_plan to REVIEW makes run_all() stop right after
    planning, before any research executes.
    """
    from src.models.approval import ApprovalPolicy
    from src.services.approval_gate_service import ApprovalGateService

    pipeline, _ = _pipeline()
    job = _job(
        approval_policy=ApprovalPolicyConfig(research_plan=ApprovalPolicy.REVIEW)
    )

    job = pipeline.run_all(job)

    assert job.research_plan is not None
    assert job.research is None

    pending = ApprovalGateService.latest_pending(job)
    assert pending is not None
    assert pending.approval is not None
    assert pending.approval.decision_point == "research_plan"


def test_resolving_research_plan_approval_unblocks_research() -> None:
    from src.models.approval import ApprovalPolicy, HumanApprovalAction
    from src.services.approval_gate_service import ApprovalGateService

    pipeline, _ = _pipeline()
    job = _job(
        approval_policy=ApprovalPolicyConfig(research_plan=ApprovalPolicy.REVIEW)
    )

    job = pipeline.run_all(job)
    assert ApprovalGateService.is_blocked(job, "research_plan") is True
    assert job.research is None

    pipeline.resolve_approval(job, "research_plan", HumanApprovalAction.APPROVE)
    assert ApprovalGateService.is_blocked(job, "research_plan") is False

    job = pipeline.run_all(job)

    assert job.research is not None


def test_run_all_is_idempotent_and_makes_no_further_llm_calls_once_complete() -> None:
    pipeline, stub = _pipeline()

    job = pipeline.run_all(_job())
    request_count_after_first_run = len(stub.requests)

    job = pipeline.run_all(job)

    assert len(stub.requests) == request_count_after_first_run
    assert job.generated_script is not None


def test_run_all_resumes_from_a_restarted_job_without_regenerating_earlier_stages() -> (
    None
):
    """
    Simulates a process restart mid-pipeline: run_all() is called on a
    job that already has audience_promise/research/story_angles set
    (e.g. reloaded from disk after a crash), and must not re-spend an
    LLM call regenerating any of them - only stages genuinely missing
    should run.
    """

    pipeline, _ = _pipeline()
    job = pipeline.run_audience_promise(_job())
    job = pipeline.run_research(job)
    job = pipeline.run_story_angles(job)

    audience_promise_before = job.audience_promise
    research_before = job.research
    selected_angle_before = job.selected_story_angle

    resumed_pipeline, stub = _pipeline()
    job = resumed_pipeline.run_all(job)

    assert job.audience_promise is audience_promise_before
    assert job.research is research_before
    assert job.selected_story_angle is selected_angle_before
    assert job.generated_script is not None

    # None of the resume calls should have re-requested audience
    # promise, research, or story-angle generation - only the stages
    # genuinely still missing (narrative architecture onward).
    agents_called = {request.metadata.get("agent") for request in stub.requests}
    assert "AudiencePromiseService" not in agents_called
    assert "ResearchAgent" not in agents_called
    assert "StoryAngleGenerationService" not in agents_called
