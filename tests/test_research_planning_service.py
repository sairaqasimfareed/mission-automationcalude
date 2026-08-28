from __future__ import annotations

import pytest

from src.models.audience_promise import AudiencePromise, PromiseStrength
from src.models.editorial_profile import EditorialProfile
from src.services.editorial_profile_composition_service import (
    EditorialProfileCompositionService,
)
from src.services.genre_profile_registry_service import (
    GenreProfileRegistryService,
)
from src.services.llm.llm_service import LLMServiceResult
from src.services.research_planning_service import ResearchPlanningService
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
        expected_payoff="The disputed final theory, weighed against evidence.",
        promise_strength=PromiseStrength.STRONG,
        prompt_version="audience_promise_prompt_v1.0.0",
    )


_DASH_QUESTIONS = (
    "- What was the ship's last confirmed position?\n"
    "- Who were the crew members aboard?\n"
    "- What official explanations have investigators offered?\n"
)


def test_plan_parses_dash_prefixed_questions() -> None:
    stub = _StubLLMService(content=_DASH_QUESTIONS)

    service = ResearchPlanningService(llm_service=stub)  # type: ignore[arg-type]

    plan = service.plan("The Mary Celeste", _promise(), _editorial_profile())

    assert len(plan.research_questions) == 3
    assert plan.research_questions[0] == "What was the ship's last confirmed position?"


def test_plan_populates_structured_questions_matching_the_flat_list() -> None:
    stub = _StubLLMService(content=_DASH_QUESTIONS)

    service = ResearchPlanningService(llm_service=stub)  # type: ignore[arg-type]

    plan = service.plan("The Mary Celeste", _promise(), _editorial_profile())

    assert len(plan.structured_questions) == len(plan.research_questions)
    assert [q.text for q in plan.structured_questions] == plan.research_questions
    # Each question has its own stable id.
    assert len({q.id for q in plan.structured_questions}) == len(
        plan.structured_questions
    )


def test_plan_parses_numbered_and_asterisk_questions() -> None:
    content = (
        "1. What was the ship's last confirmed position?\n"
        "2) Who were the crew members aboard?\n"
        "* What official explanations have investigators offered?\n"
        "Not a question line, ignored.\n"
    )

    stub = _StubLLMService(content=content)

    service = ResearchPlanningService(llm_service=stub)  # type: ignore[arg-type]

    plan = service.plan("The Mary Celeste", _promise(), _editorial_profile())

    assert len(plan.research_questions) == 3


def test_plan_deduplicates_questions() -> None:
    content = (
        "- What was the ship's last confirmed position?\n"
        "- What was the ship's last confirmed position?\n"
    )

    stub = _StubLLMService(content=content)

    service = ResearchPlanningService(llm_service=stub)  # type: ignore[arg-type]

    plan = service.plan("The Mary Celeste", _promise(), _editorial_profile())

    assert len(plan.research_questions) == 1


def test_plan_includes_promise_context_in_prompt() -> None:
    stub = _StubLLMService(content=_DASH_QUESTIONS)

    service = ResearchPlanningService(llm_service=stub)  # type: ignore[arg-type]

    service.plan("The Mary Celeste", _promise(), _editorial_profile())

    assert stub.last_request is not None
    assert "Why did the crew vanish?" in stub.last_request.prompt
    assert "What really happened aboard the ship?" in stub.last_request.prompt


def test_plan_prompt_reflects_genre_research_depth() -> None:
    medical_profile = EditorialProfileCompositionService().compose(
        genre=_GENRE_REGISTRY.get("genre.medical")
    )

    stub = _StubLLMService(content=_DASH_QUESTIONS)

    service = ResearchPlanningService(llm_service=stub)  # type: ignore[arg-type]

    service.plan("The Mary Celeste", _promise(), medical_profile)

    assert stub.last_request is not None
    assert (
        medical_profile.content_intelligence.research_policy.depth.value
        in stub.last_request.prompt
    )
    assert "Primary sources required: yes" in stub.last_request.prompt


def test_plan_raises_when_provider_fails() -> None:
    stub = _StubLLMService(content="", success=False)

    service = ResearchPlanningService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="Research planning failed"):
        service.plan("The Mary Celeste", _promise(), _editorial_profile())


def test_plan_raises_on_empty_content() -> None:
    stub = _StubLLMService(content="   ")

    service = ResearchPlanningService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="empty content"):
        service.plan("The Mary Celeste", _promise(), _editorial_profile())


def test_plan_raises_when_no_questions_parsed() -> None:
    stub = _StubLLMService(content="This response has no bullet points at all.")

    service = ResearchPlanningService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="no usable questions"):
        service.plan("The Mary Celeste", _promise(), _editorial_profile())


def test_plan_raises_on_empty_topic() -> None:
    stub = _StubLLMService(content=_DASH_QUESTIONS)

    service = ResearchPlanningService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="cannot be empty"):
        service.plan("   ", _promise(), _editorial_profile())


def test_constructor_rejects_negative_estimated_cost() -> None:
    stub = _StubLLMService(content=_DASH_QUESTIONS)

    with pytest.raises(ValueError, match="cannot be negative"):
        ResearchPlanningService(
            llm_service=stub,  # type: ignore[arg-type]
            estimated_cost_usd=-1.0,
        )


def test_dry_run_response_is_itself_parseable() -> None:
    probe = _StubLLMService(content=_DASH_QUESTIONS)

    service = ResearchPlanningService(llm_service=probe)  # type: ignore[arg-type]

    service.plan("The Mary Celeste", _promise(), _editorial_profile())

    assert probe.last_request is not None
    assert probe.last_request.dry_run_response is not None

    replay = _StubLLMService(content=probe.last_request.dry_run_response)
    replay_service = ResearchPlanningService(llm_service=replay)  # type: ignore[arg-type]

    plan = replay_service.plan("The Mary Celeste", _promise(), _editorial_profile())

    assert len(plan.research_questions) == 4
