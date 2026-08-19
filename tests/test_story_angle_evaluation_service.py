from __future__ import annotations

import pytest

from src.models.editorial_profile import EditorialProfile
from src.models.research import ResearchResult, ResearchSource, ResearchStatus
from src.models.story_angle import StoryAngle, StoryAngleStyle
from src.services.editorial_profile_composition_service import (
    EditorialProfileCompositionService,
)
from src.services.genre_profile_registry_service import (
    GenreProfileRegistryService,
)
from src.services.llm.llm_service import LLMServiceResult
from src.services.story_angle_evaluation_service import (
    StoryAngleEvaluationService,
    select_winning_evaluation,
)
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
        key_facts=["The crew was never found."],
        interesting_angles=["The missing logbook."],
        potential_hooks=["What happened to the crew?"],
        risk_notes=["Claims should be verified."],
        sources=[ResearchSource(title="Test source", confidence_score=70)],
        fact_confidence_score=70,
        prompt_version="research_prompt_v2.0.0",
        status=ResearchStatus.APPROVED,
    )


def _angles() -> list[StoryAngle]:
    return [
        StoryAngle(
            style=StoryAngleStyle.MYSTERY,
            title="The Missing Logbook",
            description="Told through the ship's missing final log entry.",
        ),
        StoryAngle(
            style=StoryAngleStyle.INVESTIGATION,
            title="Tracing the Investigators",
            description="Follows the official inquiry step by step.",
        ),
    ]


def _score_block(title: str, *, hook: int = 80, factual: int = 85) -> str:
    return (
        f"ANGLE_TITLE: {title}\n"
        f"HOOK_POTENTIAL: {hook}\n"
        "CURIOSITY: 80\n"
        "EMOTIONAL_IMPACT: 70\n"
        "ORIGINALITY: 75\n"
        f"FACTUAL_SUPPORT: {factual}\n"
        "CLARITY: 80\n"
        "TENSION: 75\n"
        "AUDIENCE_FIT: 85\n"
        "VISUAL_POTENTIAL: 70\n"
        "AUDIO_POTENTIAL: 65\n"
        "PRODUCTION_FEASIBILITY: 80\n"
        "PAYOFF_POTENTIAL: 85\n"
        "RETENTION_POTENTIAL: 80\n"
        "REASONING: Strong factual grounding and a clear unanswered question."
    )


_TWO_EVALUATION_BLOCKS = "\n---\n".join(
    [
        _score_block("The Missing Logbook", hook=90),
        _score_block("Tracing the Investigators", hook=60),
    ]
)


def test_evaluate_parses_and_matches_both_angles_by_title() -> None:
    stub = _StubLLMService(content=_TWO_EVALUATION_BLOCKS)

    service = StoryAngleEvaluationService(llm_service=stub)  # type: ignore[arg-type]

    evaluations = service.evaluate(
        topic="The Mary Celeste",
        angles=_angles(),
        research=_research(),
        editorial_profile=_editorial_profile(),
    )

    assert len(evaluations) == 2
    titles = {evaluation.angle_title for evaluation in evaluations}
    assert titles == {"The Missing Logbook", "Tracing the Investigators"}


def test_evaluate_is_case_and_whitespace_insensitive_when_matching_titles() -> None:
    content = _score_block("  the missing logbook  ")

    stub = _StubLLMService(content=content)

    service = StoryAngleEvaluationService(llm_service=stub)  # type: ignore[arg-type]

    evaluations = service.evaluate(
        topic="The Mary Celeste",
        angles=_angles(),
        research=_research(),
        editorial_profile=_editorial_profile(),
    )

    assert len(evaluations) == 1
    assert evaluations[0].angle_title == "The Missing Logbook"


def test_evaluate_skips_a_block_whose_title_does_not_match_any_angle() -> None:
    content = "\n---\n".join(
        [_score_block("Unrelated Angle"), _score_block("The Missing Logbook")]
    )

    stub = _StubLLMService(content=content)

    service = StoryAngleEvaluationService(llm_service=stub)  # type: ignore[arg-type]

    evaluations = service.evaluate(
        topic="The Mary Celeste",
        angles=_angles(),
        research=_research(),
        editorial_profile=_editorial_profile(),
    )

    assert len(evaluations) == 1
    assert evaluations[0].angle_title == "The Missing Logbook"


def test_evaluate_skips_a_block_with_an_out_of_range_score() -> None:
    bad_block = _score_block("The Missing Logbook").replace(
        "HOOK_POTENTIAL: 80", "HOOK_POTENTIAL: 150"
    )

    stub = _StubLLMService(content=bad_block)

    service = StoryAngleEvaluationService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="no usable evaluations"):
        service.evaluate(
            topic="The Mary Celeste",
            angles=_angles(),
            research=_research(),
            editorial_profile=_editorial_profile(),
        )


def test_evaluate_only_makes_one_llm_call_for_all_angles() -> None:
    """Spec section 71: avoid unnecessary LLM calls - N angles, one call."""

    stub = _StubLLMService(content=_TWO_EVALUATION_BLOCKS)

    service = StoryAngleEvaluationService(llm_service=stub)  # type: ignore[arg-type]

    service.evaluate(
        topic="The Mary Celeste",
        angles=_angles(),
        research=_research(),
        editorial_profile=_editorial_profile(),
    )

    assert stub.last_request is not None
    assert "The Missing Logbook" in stub.last_request.prompt
    assert "Tracing the Investigators" in stub.last_request.prompt


def test_evaluate_system_prompt_reflects_genre_quality_bar() -> None:
    medical_profile = EditorialProfileCompositionService().compose(
        genre=_GENRE_REGISTRY.get("genre.medical")
    )

    stub = _StubLLMService(content=_TWO_EVALUATION_BLOCKS)

    service = StoryAngleEvaluationService(llm_service=stub)  # type: ignore[arg-type]

    service.evaluate(
        topic="The Mary Celeste",
        angles=_angles(),
        research=_research(),
        editorial_profile=medical_profile,
    )

    assert stub.last_request is not None
    assert stub.last_request.system_prompt is not None
    assert "genre.medical" in stub.last_request.system_prompt
    assert "factual_confidence>=75" in stub.last_request.system_prompt


def test_evaluate_raises_on_empty_angle_list() -> None:
    stub = _StubLLMService(content=_TWO_EVALUATION_BLOCKS)

    service = StoryAngleEvaluationService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="At least one story angle"):
        service.evaluate(
            topic="The Mary Celeste",
            angles=[],
            research=_research(),
            editorial_profile=_editorial_profile(),
        )


def test_evaluate_raises_when_provider_fails() -> None:
    stub = _StubLLMService(content="", success=False)

    service = StoryAngleEvaluationService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="Story angle evaluation failed"):
        service.evaluate(
            topic="The Mary Celeste",
            angles=_angles(),
            research=_research(),
            editorial_profile=_editorial_profile(),
        )


def test_constructor_rejects_negative_estimated_cost() -> None:
    stub = _StubLLMService(content=_TWO_EVALUATION_BLOCKS)

    with pytest.raises(ValueError, match="cannot be negative"):
        StoryAngleEvaluationService(
            llm_service=stub,  # type: ignore[arg-type]
            estimated_cost_usd=-1.0,
        )


def test_dry_run_response_is_itself_parseable() -> None:
    probe = _StubLLMService(content=_TWO_EVALUATION_BLOCKS)

    service = StoryAngleEvaluationService(llm_service=probe)  # type: ignore[arg-type]

    service.evaluate(
        topic="The Mary Celeste",
        angles=_angles(),
        research=_research(),
        editorial_profile=_editorial_profile(),
    )

    assert probe.last_request is not None
    assert probe.last_request.dry_run_response is not None

    replay = _StubLLMService(content=probe.last_request.dry_run_response)
    replay_service = StoryAngleEvaluationService(llm_service=replay)  # type: ignore[arg-type]

    evaluations = replay_service.evaluate(
        topic="The Mary Celeste",
        angles=_angles(),
        research=_research(),
        editorial_profile=_editorial_profile(),
    )

    assert len(evaluations) == 2


def test_select_winning_evaluation_picks_the_highest_overall_score() -> None:
    stub = _StubLLMService(content=_TWO_EVALUATION_BLOCKS)

    service = StoryAngleEvaluationService(llm_service=stub)  # type: ignore[arg-type]

    evaluations = service.evaluate(
        topic="The Mary Celeste",
        angles=_angles(),
        research=_research(),
        editorial_profile=_editorial_profile(),
    )

    winner = select_winning_evaluation(evaluations)

    # "The Missing Logbook" was given hook=90 vs. the other's hook=60,
    # so it should have the higher overall_score and win.
    assert winner.angle_title == "The Missing Logbook"


def test_select_winning_evaluation_raises_on_empty_list() -> None:
    with pytest.raises(ValueError, match="At least one evaluation"):
        select_winning_evaluation([])
