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
from src.services.information_reveal_planning_service import (
    InformationRevealPlanningService,
)
from src.services.llm.llm_service import LLMServiceResult
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


def _angle() -> StoryAngle:
    return StoryAngle(
        style=StoryAngleStyle.MYSTERY,
        title="The Missing Logbook",
        description="Told through the ship's missing final log entry.",
    )


_FULL_RESPONSE = (
    "TYPE: loop\n"
    "QUESTION: Why did the crew vanish?\n"
    "OPENED_AT: 0.05\n"
    "ALLOW_EARLY_RESOLUTION: no\n"
    "---\n"
    "TYPE: loop\n"
    "QUESTION: What happened to the logbook?\n"
    "OPENED_AT: 0.2\n"
    "ALLOW_EARLY_RESOLUTION: no\n"
    "---\n"
    "TYPE: reveal\n"
    "POSITION: 0.9\n"
    "INFORMATION: The most plausible theory, weighed against evidence.\n"
    "ESCALATES: no\n"
    "IS_PAYOFF: yes\n"
    "RELATED_QUESTION: Why did the crew vanish?"
)


def test_plan_parses_loops_and_reveals() -> None:
    stub = _StubLLMService(content=_FULL_RESPONSE)

    service = InformationRevealPlanningService(llm_service=stub)  # type: ignore[arg-type]

    reveal_map = service.plan(
        topic="The Mary Celeste",
        story_angle=_angle(),
        research=_research(),
        editorial_profile=_editorial_profile(),
        target_duration_seconds=180,
    )

    assert len(reveal_map.curiosity_loops) == 2
    assert reveal_map.curiosity_loops[0].question == "Why did the crew vanish?"
    assert reveal_map.curiosity_loops[0].opened_at_position == 0.05
    assert len(reveal_map.reveals) == 1
    assert reveal_map.reveals[0].is_payoff is True
    assert reveal_map.reveals[0].related_question == "Why did the crew vanish?"


def test_plan_treats_none_related_question_as_none() -> None:
    content = (
        "TYPE: loop\n"
        "QUESTION: Why did the crew vanish?\n"
        "OPENED_AT: 0.05\n"
        "ALLOW_EARLY_RESOLUTION: no\n"
        "---\n"
        "TYPE: reveal\n"
        "POSITION: 0.5\n"
        "INFORMATION: A minor detail.\n"
        "ESCALATES: no\n"
        "IS_PAYOFF: no\n"
        "RELATED_QUESTION: none"
    )

    stub = _StubLLMService(content=content)

    service = InformationRevealPlanningService(llm_service=stub)  # type: ignore[arg-type]

    reveal_map = service.plan(
        topic="The Mary Celeste",
        story_angle=_angle(),
        research=_research(),
        editorial_profile=_editorial_profile(),
        target_duration_seconds=180,
    )

    assert reveal_map.reveals[0].related_question is None


def test_plan_skips_a_block_with_an_out_of_range_position() -> None:
    content = (
        "TYPE: loop\n"
        "QUESTION: Why did the crew vanish?\n"
        "OPENED_AT: 1.5\n"
        "ALLOW_EARLY_RESOLUTION: no\n"
        "---\n"
        "TYPE: loop\n"
        "QUESTION: What happened to the logbook?\n"
        "OPENED_AT: 0.2\n"
        "ALLOW_EARLY_RESOLUTION: no"
    )

    stub = _StubLLMService(content=content)

    service = InformationRevealPlanningService(llm_service=stub)  # type: ignore[arg-type]

    reveal_map = service.plan(
        topic="The Mary Celeste",
        story_angle=_angle(),
        research=_research(),
        editorial_profile=_editorial_profile(),
        target_duration_seconds=180,
    )

    assert len(reveal_map.curiosity_loops) == 1
    assert reveal_map.curiosity_loops[0].question == "What happened to the logbook?"


def test_plan_ignores_unrecognized_block_types() -> None:
    content = (
        "TYPE: something_else\n"
        "QUESTION: Should be ignored.\n"
        "---\n"
        "TYPE: loop\n"
        "QUESTION: Why did the crew vanish?\n"
        "OPENED_AT: 0.05\n"
        "ALLOW_EARLY_RESOLUTION: no"
    )

    stub = _StubLLMService(content=content)

    service = InformationRevealPlanningService(llm_service=stub)  # type: ignore[arg-type]

    reveal_map = service.plan(
        topic="The Mary Celeste",
        story_angle=_angle(),
        research=_research(),
        editorial_profile=_editorial_profile(),
        target_duration_seconds=180,
    )

    assert len(reveal_map.curiosity_loops) == 1


def test_plan_prompt_reflects_genre_reveal_density() -> None:
    top10_profile = EditorialProfileCompositionService().compose(
        genre=_GENRE_REGISTRY.get("genre.top10")
    )

    stub = _StubLLMService(content=_FULL_RESPONSE)

    service = InformationRevealPlanningService(llm_service=stub)  # type: ignore[arg-type]

    service.plan(
        topic="The Mary Celeste",
        story_angle=_angle(),
        research=_research(),
        editorial_profile=top10_profile,
        target_duration_seconds=180,
    )

    assert stub.last_request is not None
    # top10's reveal_density_per_minute is 4.0, so a 180s (3 minute)
    # video targets ~12 combined loops/reveals.
    assert "approximately 12" in stub.last_request.prompt


def test_plan_raises_on_non_positive_duration() -> None:
    stub = _StubLLMService(content=_FULL_RESPONSE)

    service = InformationRevealPlanningService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="must be positive"):
        service.plan(
            topic="The Mary Celeste",
            story_angle=_angle(),
            research=_research(),
            editorial_profile=_editorial_profile(),
            target_duration_seconds=0,
        )


def test_plan_raises_when_provider_fails() -> None:
    stub = _StubLLMService(content="", success=False)

    service = InformationRevealPlanningService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="Information reveal planning failed"):
        service.plan(
            topic="The Mary Celeste",
            story_angle=_angle(),
            research=_research(),
            editorial_profile=_editorial_profile(),
            target_duration_seconds=180,
        )


def test_plan_raises_when_no_loops_parsed() -> None:
    stub = _StubLLMService(content="This response has no valid blocks at all.")

    service = InformationRevealPlanningService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="no usable curiosity loops"):
        service.plan(
            topic="The Mary Celeste",
            story_angle=_angle(),
            research=_research(),
            editorial_profile=_editorial_profile(),
            target_duration_seconds=180,
        )


def test_plan_raises_on_empty_topic() -> None:
    stub = _StubLLMService(content=_FULL_RESPONSE)

    service = InformationRevealPlanningService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="cannot be empty"):
        service.plan(
            topic="   ",
            story_angle=_angle(),
            research=_research(),
            editorial_profile=_editorial_profile(),
            target_duration_seconds=180,
        )


def test_constructor_rejects_negative_estimated_cost() -> None:
    stub = _StubLLMService(content=_FULL_RESPONSE)

    with pytest.raises(ValueError, match="cannot be negative"):
        InformationRevealPlanningService(
            llm_service=stub,  # type: ignore[arg-type]
            estimated_cost_usd=-1.0,
        )


def test_dry_run_response_is_itself_parseable() -> None:
    probe = _StubLLMService(content=_FULL_RESPONSE)

    service = InformationRevealPlanningService(llm_service=probe)  # type: ignore[arg-type]

    service.plan(
        topic="The Mary Celeste",
        story_angle=_angle(),
        research=_research(),
        editorial_profile=_editorial_profile(),
        target_duration_seconds=180,
    )

    assert probe.last_request is not None
    assert probe.last_request.dry_run_response is not None

    replay = _StubLLMService(content=probe.last_request.dry_run_response)
    replay_service = InformationRevealPlanningService(llm_service=replay)  # type: ignore[arg-type]

    reveal_map = replay_service.plan(
        topic="The Mary Celeste",
        story_angle=_angle(),
        research=_research(),
        editorial_profile=_editorial_profile(),
        target_duration_seconds=180,
    )

    assert len(reveal_map.curiosity_loops) == 1
    assert len(reveal_map.reveals) == 1
