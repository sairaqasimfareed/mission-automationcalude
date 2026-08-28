from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.genre_profile import ResearchPolicy
from src.models.research_plan import ResearchPlan, ResearchQuestion


def test_valid_plan_constructs() -> None:
    plan = ResearchPlan(
        topic="The Mary Celeste",
        research_questions=["What happened to the crew?"],
        prompt_version="research_plan_prompt_v1.0.0",
    )

    assert plan.research_questions == ["What happened to the crew?"]


def test_deduplicates_questions() -> None:
    plan = ResearchPlan(
        topic="The Mary Celeste",
        research_questions=[
            "What happened to the crew?",
            "What happened to the crew?",
            "  What happened to the crew?  ",
        ],
        prompt_version="research_plan_prompt_v1.0.0",
    )

    assert plan.research_questions == ["What happened to the crew?"]


def test_strips_blank_questions() -> None:
    plan = ResearchPlan(
        topic="The Mary Celeste",
        research_questions=["What happened to the crew?", "   ", ""],
        prompt_version="research_plan_prompt_v1.0.0",
    )

    assert plan.research_questions == ["What happened to the crew?"]


def test_requires_at_least_one_question() -> None:
    with pytest.raises(ValidationError):
        ResearchPlan(
            topic="The Mary Celeste",
            research_questions=[],
            prompt_version="research_plan_prompt_v1.0.0",
        )


def test_all_blank_questions_fails_the_min_length_check() -> None:
    with pytest.raises(ValidationError, match="at least one question"):
        ResearchPlan(
            topic="The Mary Celeste",
            research_questions=["   ", ""],
            prompt_version="research_plan_prompt_v1.0.0",
        )


def test_phase_7_fields_default_to_empty() -> None:
    plan = ResearchPlan(
        topic="The Mary Celeste",
        research_questions=["What happened to the crew?"],
        prompt_version="research_plan_prompt_v1.0.0",
    )

    assert plan.structured_questions == []
    assert plan.research_policy_override is None
    assert plan.user_constraints == []


def test_structured_questions_carry_stable_ids() -> None:
    question = ResearchQuestion(text="What happened to the crew?")
    plan = ResearchPlan(
        topic="The Mary Celeste",
        research_questions=["What happened to the crew?"],
        structured_questions=[question],
        prompt_version="research_plan_prompt_v1.0.0",
    )

    assert plan.structured_questions[0].id == question.id
    assert plan.structured_questions[0].text == "What happened to the crew?"


def test_research_question_rejects_blank_text() -> None:
    with pytest.raises(ValidationError, match="cannot be empty"):
        ResearchQuestion(text="   ")


def test_user_constraints_strip_whitespace_and_drop_blank_entries() -> None:
    plan = ResearchPlan(
        topic="The Mary Celeste",
        research_questions=["What happened to the crew?"],
        prompt_version="research_plan_prompt_v1.0.0",
        user_constraints=["  Avoid speculation  ", "", "   "],
    )

    assert plan.user_constraints == ["Avoid speculation"]


def test_research_policy_override_can_be_set() -> None:
    override = ResearchPolicy(minimum_source_count=5, requires_primary_sources=True)
    plan = ResearchPlan(
        topic="The Mary Celeste",
        research_questions=["What happened to the crew?"],
        prompt_version="research_plan_prompt_v1.0.0",
        research_policy_override=override,
    )

    assert plan.research_policy_override is not None
    assert plan.research_policy_override.minimum_source_count == 5
    assert plan.research_policy_override.requires_primary_sources is True


def test_backward_compatible_round_trip_without_phase_7_fields() -> None:
    """
    A VideoJob JSON file saved before Phase 7 has no structured_
    questions/research_policy_override/user_constraints keys at all -
    Pydantic's defaults must absorb that silently rather than raising.
    """

    plan = ResearchPlan(
        topic="The Mary Celeste",
        research_questions=["What happened to the crew?"],
        prompt_version="research_plan_prompt_v1.0.0",
    )
    raw = plan.model_dump_json()

    reloaded = ResearchPlan.model_validate_json(raw)

    assert reloaded.structured_questions == []
    assert reloaded.research_policy_override is None
    assert reloaded.user_constraints == []
