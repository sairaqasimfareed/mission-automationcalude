from __future__ import annotations

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel
from src.models.genre_profile import ResearchPolicy


class ResearchQuestion(MissionBaseModel):
    """
    One research question with a stable identity (Content Studio
    Redesign, Phase 7: Research Center) - `id` is inherited from
    MissionBaseModel and never changes across an edit, only across a
    removal, so the GUI's Add/Edit/Remove actions can target one
    question without relying on list position.
    """

    text: str = Field(min_length=1)

    @field_validator("text")
    @classmethod
    def clean_text(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Research question text cannot be empty.")

        return cleaned


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

    # Content Studio Redesign, Phase 7 additions. structured_questions
    # is kept alongside research_questions above rather than replacing
    # it - research_questions stays the flat list every existing
    # caller and test already reads; structured_questions is the new,
    # stable-ID-bearing representation the GUI's Add/Edit/Remove
    # actions operate on. Callers that edit questions are responsible
    # for keeping research_questions in sync (see
    # ContentStudioView's research-question handlers) - this model
    # does not enforce that itself, matching this codebase's existing
    # convention of validating in the caller rather than via
    # validate_assignment.
    structured_questions: list[ResearchQuestion] = Field(default_factory=list)

    # A per-brief override of the genre's default ResearchPolicy - None
    # means "use the genre default unchanged". Kept as a separate,
    # optional field rather than always-populated so a brief that never
    # customizes policy stays indistinguishable from one that
    # deliberately re-selected the genre default.
    research_policy_override: ResearchPolicy | None = None

    user_constraints: list[str] = Field(default_factory=list)

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

    @field_validator("user_constraints")
    @classmethod
    def clean_user_constraints(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]

        return [value for value in cleaned if value]
