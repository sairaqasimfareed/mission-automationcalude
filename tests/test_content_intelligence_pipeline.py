from __future__ import annotations

from uuid import uuid4

import pytest

from src.models.approval import ApprovalPolicyConfig
from src.models.script_lock import ScriptProvenance
from src.models.script_selection_edit import (
    SelectionEditOperation,
    SelectionEditRequest,
)
from src.models.script_version import VersionReason
from src.models.video_job import VideoJob
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
    return VideoJob(**base)


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
