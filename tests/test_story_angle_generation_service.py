from __future__ import annotations

import pytest

from src.models.audience_promise import AudiencePromise, PromiseStrength
from src.models.research import ResearchResult, ResearchSource, ResearchStatus
from src.models.story_angle import StoryAngleStyle
from src.services.llm.llm_service import LLMServiceResult
from src.services.story_angle_generation_service import StoryAngleGenerationService
from src.shared.llm.models import LLMCallResult, LLMCallStatus, LLMProvider
from src.shared.llm.request import LLMRequest


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
        target_duration_seconds=180,
        intended_emotion="Dread",
        central_curiosity="Why did the crew vanish?",
        primary_question="What really happened aboard the ship?",
        viewer_benefit="A satisfying, verified explanation.",
        expected_payoff="The disputed final theory.",
        promise_strength=PromiseStrength.STRONG,
        prompt_version="audience_promise_prompt_v1.0.0",
    )


_TWO_ANGLE_BLOCK = (
    "STYLE: mystery\n"
    "TITLE: The Missing Logbook\n"
    "DESCRIPTION: Told through the ship's missing final log entry.\n"
    "---\n"
    "style: investigation\n"
    "title: Tracing the Investigators\n"
    "description: Follows the official inquiry step by step."
)


def test_generate_parses_multiple_angle_blocks() -> None:
    stub = _StubLLMService(content=_TWO_ANGLE_BLOCK)

    service = StoryAngleGenerationService(llm_service=stub)  # type: ignore[arg-type]

    angles = service.generate(
        topic="The Mary Celeste",
        research=_research(),
        audience_promise=_promise(),
        angle_count=2,
    )

    assert len(angles) == 2
    assert angles[0].style == StoryAngleStyle.MYSTERY
    assert angles[0].title == "The Missing Logbook"
    assert angles[1].style == StoryAngleStyle.INVESTIGATION


def test_generate_truncates_to_angle_count() -> None:
    stub = _StubLLMService(content=_TWO_ANGLE_BLOCK)

    service = StoryAngleGenerationService(llm_service=stub)  # type: ignore[arg-type]

    angles = service.generate(
        topic="The Mary Celeste",
        research=_research(),
        audience_promise=_promise(),
        angle_count=1,
    )

    assert len(angles) == 1


def test_generate_skips_blocks_with_an_unrecognized_style() -> None:
    content = (
        "STYLE: not_a_real_style\n"
        "TITLE: Bad Angle\n"
        "DESCRIPTION: Should be skipped.\n"
        "---\n"
        "STYLE: horror\n"
        "TITLE: The Dread Below\n"
        "DESCRIPTION: A horror-focused framing."
    )

    stub = _StubLLMService(content=content)

    service = StoryAngleGenerationService(llm_service=stub)  # type: ignore[arg-type]

    angles = service.generate(
        topic="The Mary Celeste",
        research=_research(),
        audience_promise=_promise(),
        angle_count=5,
    )

    assert len(angles) == 1
    assert angles[0].title == "The Dread Below"


def test_generate_includes_research_and_promise_context_in_prompt() -> None:
    stub = _StubLLMService(content=_TWO_ANGLE_BLOCK)

    service = StoryAngleGenerationService(llm_service=stub)  # type: ignore[arg-type]

    service.generate(
        topic="The Mary Celeste",
        research=_research(),
        audience_promise=_promise(),
    )

    assert stub.last_request is not None
    assert "Why did the crew vanish?" in stub.last_request.prompt
    assert "crew was never found" in stub.last_request.prompt.lower()


def test_generate_raises_when_provider_fails() -> None:
    stub = _StubLLMService(content="", success=False)

    service = StoryAngleGenerationService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="Story angle generation failed"):
        service.generate(
            topic="The Mary Celeste",
            research=_research(),
            audience_promise=_promise(),
        )


def test_generate_raises_when_no_valid_angles_parsed() -> None:
    stub = _StubLLMService(content="This is not formatted correctly at all.")

    service = StoryAngleGenerationService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="no usable angles"):
        service.generate(
            topic="The Mary Celeste",
            research=_research(),
            audience_promise=_promise(),
        )


def test_generate_rejects_angle_count_below_one() -> None:
    stub = _StubLLMService(content=_TWO_ANGLE_BLOCK)

    service = StoryAngleGenerationService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="at least 1"):
        service.generate(
            topic="The Mary Celeste",
            research=_research(),
            audience_promise=_promise(),
            angle_count=0,
        )


def test_constructor_rejects_negative_estimated_cost() -> None:
    stub = _StubLLMService(content=_TWO_ANGLE_BLOCK)

    with pytest.raises(ValueError, match="cannot be negative"):
        StoryAngleGenerationService(
            llm_service=stub,  # type: ignore[arg-type]
            estimated_cost_usd=-1.0,
        )


def test_dry_run_response_is_itself_parseable() -> None:
    probe = _StubLLMService(content=_TWO_ANGLE_BLOCK)

    service = StoryAngleGenerationService(llm_service=probe)  # type: ignore[arg-type]

    service.generate(
        topic="The Mary Celeste",
        research=_research(),
        audience_promise=_promise(),
        angle_count=3,
    )

    assert probe.last_request is not None
    assert probe.last_request.dry_run_response is not None

    replay = _StubLLMService(content=probe.last_request.dry_run_response)
    replay_service = StoryAngleGenerationService(llm_service=replay)  # type: ignore[arg-type]

    angles = replay_service.generate(
        topic="The Mary Celeste",
        research=_research(),
        audience_promise=_promise(),
        angle_count=3,
    )

    assert len(angles) == 3
