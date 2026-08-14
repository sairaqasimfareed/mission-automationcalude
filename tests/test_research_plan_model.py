from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.research_plan import ResearchPlan


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
