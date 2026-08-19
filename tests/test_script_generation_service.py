from __future__ import annotations

import pytest

from src.models.audience_promise import AudiencePromise, PromiseStrength
from src.models.editorial_profile import EditorialProfile
from src.models.hook import HookEvaluation
from src.models.information_reveal_map import CuriosityLoop, InformationRevealMap
from src.models.re_hook import ReHook, ReHookPlan, ReHookType
from src.models.research import ResearchResult, ResearchSource, ResearchStatus
from src.models.story_angle import StoryAngle, StoryAngleStyle
from src.models.story_blueprint import StoryBeat, StoryBeatType, StoryBlueprint
from src.services.editorial_profile_composition_service import (
    EditorialProfileCompositionService,
)
from src.services.genre_profile_registry_service import (
    GenreProfileRegistryService,
)
from src.services.llm.llm_service import LLMServiceResult
from src.services.script_generation_service import ScriptGenerationService
from src.shared.llm.models import LLMCallResult, LLMCallStatus, LLMProvider
from src.shared.llm.request import LLMRequest

_GENRE_REGISTRY = GenreProfileRegistryService.with_default_profiles()


def _editorial_profile() -> EditorialProfile:
    return EditorialProfileCompositionService().compose(
        genre=_GENRE_REGISTRY.get("genre.mystery")
    )


class _StubLLMService:
    def __init__(self, *, content: str, success: bool = True) -> None:
        self._content = content
        self._success = success
        self.last_request: LLMRequest | None = None

    def generate(
        self,
        request: LLMRequest,
        *,
        estimated_cost_usd: float = 0.0,
        profile_ids: list[str] | None = None,
    ) -> LLMServiceResult:
        self.last_request = request

        status = (
            LLMCallStatus.SUCCESS if self._success else LLMCallStatus.PROVIDER_ERROR
        )

        result = LLMCallResult(
            status=status,
            provider=LLMProvider.OPENAI,
            model="test-model",
            content=self._content if self._success else None,
            error_message=None if self._success else "Provider unavailable.",
        )

        return LLMServiceResult(
            result=result,
            selected_profile_id="openai-main" if self._success else None,
            all_providers_failed=not self._success,
        )


def _research() -> ResearchResult:
    return ResearchResult(
        topic="The Mary Celeste",
        research_summary="An overview of the ship's disappearance.",
        key_facts=["The crew was never found.", "The ship was seaworthy."],
        interesting_angles=["The missing logbook."],
        potential_hooks=["What happened to the crew?"],
        risk_notes=["Claims should be verified."],
        sources=[ResearchSource(title="Test source", confidence_score=70)],
        fact_confidence_score=70,
        prompt_version="research_prompt_v2.0.0",
        status=ResearchStatus.APPROVED,
    )


def _promise() -> AudiencePromise:
    return AudiencePromise(
        topic="The Mary Celeste",
        target_audience="Mystery enthusiasts",
        platform="youtube",
        genre_id="genre.mystery",
        target_duration_seconds=30,
        intended_emotion="Dread",
        central_curiosity="Why did the crew vanish?",
        primary_question="What really happened aboard the ship?",
        viewer_benefit="A satisfying, verified explanation.",
        expected_payoff="The disputed final theory.",
        promise_strength=PromiseStrength.STRONG,
        prompt_version="audience_promise_prompt_v1.0.0",
    )


def _angle() -> StoryAngle:
    return StoryAngle(
        style=StoryAngleStyle.MYSTERY,
        title="The Missing Logbook",
        description="Told through the ship's missing final log entry.",
    )


def _blueprint() -> StoryBlueprint:
    return StoryBlueprint(
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        target_duration_seconds=30,
        beats=[
            StoryBeat(
                beat_type=StoryBeatType.HOOK,
                start_seconds=0,
                end_seconds=7,
                purpose="Open cold.",
                tension_level=60,
            ),
            StoryBeat(
                beat_type=StoryBeatType.RE_HOOK,
                start_seconds=7,
                end_seconds=10,
                purpose="Re-establish curiosity.",
                tension_level=50,
            ),
            StoryBeat(
                beat_type=StoryBeatType.PAYOFF,
                start_seconds=10,
                end_seconds=30,
                purpose="Resolve the mystery.",
                tension_level=80,
            ),
        ],
        prompt_version="story_blueprint_prompt_v1.0.0",
    )


def _reveal_map() -> InformationRevealMap:
    return InformationRevealMap(
        topic="The Mary Celeste",
        curiosity_loops=[
            CuriosityLoop(question="Why did the crew vanish?", opened_at_position=0.0)
        ],
        prompt_version="v1",
    )


def _winning_hook() -> HookEvaluation:
    return HookEvaluation(
        hook_text="The crew vanished without a trace.",
        immediate_curiosity=90,
        specificity=80,
        stakes=75,
        clarity=80,
        emotional_impact=70,
        novelty=75,
        relevance=85,
        audience_fit=80,
        factual_support=90,
        spoiler_risk=10,
        reasoning="Strong, specific hook.",
    )


def _re_hook_plan() -> ReHookPlan:
    return ReHookPlan(
        topic="The Mary Celeste",
        re_hooks=[
            ReHook(
                position_seconds=7,
                re_hook_type=ReHookType.NEW_QUESTION,
                text="But the logbook raised a bigger question.",
            )
        ],
        prompt_version="v1",
    )


_THREE_SEGMENT_RESPONSE = "\n---\n".join(
    [
        "SEGMENT: 1\nNARRATION: The crew vanished without a trace.\nRELATED_QUESTION: Why did the crew vanish?\nCLAIMS: crew was never found",
        "SEGMENT: 2\nNARRATION: But the logbook raised a bigger question.\nRELATED_QUESTION: none\nCLAIMS: none",
        "SEGMENT: 3\nNARRATION: The most likely theory is a waterspout scare.\nRELATED_QUESTION: Why did the crew vanish?\nCLAIMS: ship was seaworthy",
    ]
)


def _generate(stub: _StubLLMService) -> ScriptGenerationService:
    return ScriptGenerationService(llm_service=stub)  # type: ignore[arg-type]


def test_generate_produces_one_segment_per_blueprint_beat() -> None:
    stub = _StubLLMService(content=_THREE_SEGMENT_RESPONSE)

    script = _generate(stub).generate(
        topic="The Mary Celeste",
        editorial_profile=_editorial_profile(),
        research=_research(),
        audience_promise=_promise(),
        story_angle=_angle(),
        blueprint=_blueprint(),
        reveal_map=_reveal_map(),
        winning_hook=_winning_hook(),
        re_hook_plan=_re_hook_plan(),
    )

    assert len(script.segments) == 3


def test_generate_inherits_timing_and_structural_role_from_blueprint() -> None:
    """
    Confirms the service never lets the LLM redecide upstream facts
    (spec section 32) - timing/tension/narrative_function come from
    the blueprint beat, not from anything the stub LLM returned.
    """

    stub = _StubLLMService(content=_THREE_SEGMENT_RESPONSE)

    script = _generate(stub).generate(
        topic="The Mary Celeste",
        editorial_profile=_editorial_profile(),
        research=_research(),
        audience_promise=_promise(),
        story_angle=_angle(),
        blueprint=_blueprint(),
        reveal_map=_reveal_map(),
        winning_hook=_winning_hook(),
        re_hook_plan=_re_hook_plan(),
    )

    hook_segment = script.segments[0]
    assert hook_segment.start_seconds == 0.0
    assert hook_segment.end_seconds == 7.0
    assert hook_segment.narrative_function == StoryBeatType.HOOK
    assert hook_segment.tension_level == 60


def test_generate_parses_related_question_and_claims() -> None:
    stub = _StubLLMService(content=_THREE_SEGMENT_RESPONSE)

    script = _generate(stub).generate(
        topic="The Mary Celeste",
        editorial_profile=_editorial_profile(),
        research=_research(),
        audience_promise=_promise(),
        story_angle=_angle(),
        blueprint=_blueprint(),
        reveal_map=_reveal_map(),
        winning_hook=_winning_hook(),
        re_hook_plan=_re_hook_plan(),
    )

    assert script.segments[0].related_curiosity_loop == "Why did the crew vanish?"
    assert script.segments[0].source_claim_references == ["crew was never found"]
    assert script.segments[1].related_curiosity_loop is None


def test_generate_includes_hook_and_re_hook_text_in_prompt() -> None:
    stub = _StubLLMService(content=_THREE_SEGMENT_RESPONSE)

    _generate(stub).generate(
        topic="The Mary Celeste",
        editorial_profile=_editorial_profile(),
        research=_research(),
        audience_promise=_promise(),
        story_angle=_angle(),
        blueprint=_blueprint(),
        reveal_map=_reveal_map(),
        winning_hook=_winning_hook(),
        re_hook_plan=_re_hook_plan(),
    )

    assert stub.last_request is not None
    assert "The crew vanished without a trace." in stub.last_request.prompt
    assert "But the logbook raised a bigger question." in stub.last_request.prompt


def test_generate_prompt_reflects_genre_style() -> None:
    stub = _StubLLMService(content=_THREE_SEGMENT_RESPONSE)

    profile = _editorial_profile()

    _generate(stub).generate(
        topic="The Mary Celeste",
        editorial_profile=profile,
        research=_research(),
        audience_promise=_promise(),
        story_angle=_angle(),
        blueprint=_blueprint(),
        reveal_map=_reveal_map(),
        winning_hook=_winning_hook(),
        re_hook_plan=_re_hook_plan(),
    )

    assert stub.last_request is not None
    assert stub.last_request.system_prompt is not None
    assert profile.genre_id in stub.last_request.system_prompt
    assert profile.script.tone.value in stub.last_request.system_prompt
    assert profile.script.slang_intensity.value in stub.last_request.system_prompt
    assert (
        "slang-transformed" in stub.last_request.system_prompt
    )  # never-slang-evidence rule always present


def test_generate_works_without_a_re_hook_plan() -> None:
    stub = _StubLLMService(content=_THREE_SEGMENT_RESPONSE)

    script = _generate(stub).generate(
        topic="The Mary Celeste",
        editorial_profile=_editorial_profile(),
        research=_research(),
        audience_promise=_promise(),
        story_angle=_angle(),
        blueprint=_blueprint(),
        reveal_map=_reveal_map(),
        winning_hook=_winning_hook(),
        re_hook_plan=None,
    )

    assert len(script.segments) == 3


def test_generate_skips_a_segment_number_outside_the_beat_range() -> None:
    content = "\n---\n".join(
        [
            "SEGMENT: 99\nNARRATION: Out of range.\nRELATED_QUESTION: none\nCLAIMS: none",
            "SEGMENT: 1\nNARRATION: The crew vanished without a trace.\nRELATED_QUESTION: none\nCLAIMS: none",
        ]
    )

    stub = _StubLLMService(content=content)

    script = _generate(stub).generate(
        topic="The Mary Celeste",
        editorial_profile=_editorial_profile(),
        research=_research(),
        audience_promise=_promise(),
        story_angle=_angle(),
        blueprint=_blueprint(),
        reveal_map=_reveal_map(),
        winning_hook=_winning_hook(),
    )

    assert len(script.segments) == 1


def test_generate_raises_when_provider_fails() -> None:
    stub = _StubLLMService(content="", success=False)

    with pytest.raises(RuntimeError, match="Script generation failed"):
        _generate(stub).generate(
            topic="The Mary Celeste",
            editorial_profile=_editorial_profile(),
            research=_research(),
            audience_promise=_promise(),
            story_angle=_angle(),
            blueprint=_blueprint(),
            reveal_map=_reveal_map(),
            winning_hook=_winning_hook(),
        )


def test_generate_raises_when_no_segments_parsed() -> None:
    stub = _StubLLMService(content="This response has no valid blocks at all.")

    with pytest.raises(RuntimeError, match="no usable segments"):
        _generate(stub).generate(
            topic="The Mary Celeste",
            editorial_profile=_editorial_profile(),
            research=_research(),
            audience_promise=_promise(),
            story_angle=_angle(),
            blueprint=_blueprint(),
            reveal_map=_reveal_map(),
            winning_hook=_winning_hook(),
        )


def test_generate_raises_on_empty_topic() -> None:
    stub = _StubLLMService(content=_THREE_SEGMENT_RESPONSE)

    with pytest.raises(ValueError, match="cannot be empty"):
        _generate(stub).generate(
            topic="   ",
            editorial_profile=_editorial_profile(),
            research=_research(),
            audience_promise=_promise(),
            story_angle=_angle(),
            blueprint=_blueprint(),
            reveal_map=_reveal_map(),
            winning_hook=_winning_hook(),
        )


def test_constructor_rejects_negative_estimated_cost() -> None:
    stub = _StubLLMService(content=_THREE_SEGMENT_RESPONSE)

    with pytest.raises(ValueError, match="cannot be negative"):
        ScriptGenerationService(
            llm_service=stub,  # type: ignore[arg-type]
            estimated_cost_usd=-1.0,
        )


def test_dry_run_response_is_itself_parseable() -> None:
    probe = _StubLLMService(content=_THREE_SEGMENT_RESPONSE)

    _generate(probe).generate(
        topic="The Mary Celeste",
        editorial_profile=_editorial_profile(),
        research=_research(),
        audience_promise=_promise(),
        story_angle=_angle(),
        blueprint=_blueprint(),
        reveal_map=_reveal_map(),
        winning_hook=_winning_hook(),
        re_hook_plan=_re_hook_plan(),
    )

    assert probe.last_request is not None
    assert probe.last_request.dry_run_response is not None

    replay = _StubLLMService(content=probe.last_request.dry_run_response)

    script = _generate(replay).generate(
        topic="The Mary Celeste",
        editorial_profile=_editorial_profile(),
        research=_research(),
        audience_promise=_promise(),
        story_angle=_angle(),
        blueprint=_blueprint(),
        reveal_map=_reveal_map(),
        winning_hook=_winning_hook(),
        re_hook_plan=_re_hook_plan(),
    )

    assert len(script.segments) == 3
