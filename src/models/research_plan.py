from __future__ import annotations

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel


class ResearchPlan(MissionBaseModel):
    """
    What should be researched for one topic, decided before deep
    research begins (spec section 13), so research stays purposeful
    and aligned with the topic's audience promise rather than an
    uncontrolled information dump.
    """

    topic: str = Field(min_length=1)
    research_questions: list[str] = Field(min_length=1)
    prompt_version: str = Field(min_length=1)

    @field_validator("research_questions")
    @classmethod
    def clean_research_questions(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []

        for value in values:
            question = value.strip()

            if question and question not in cleaned:
                cleaned.append(question)

        if not cleaned:
            raise ValueError("A research plan requires at least one question.")

        return cleaned
