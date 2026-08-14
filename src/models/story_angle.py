from __future__ import annotations

from enum import Enum

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel

# Below this factual_support score, an angle's overall_score is
# capped at its own factual_support - spec section 22: "Factual
# integrity must override engagement optimization." An angle cannot
# rank highly on hook/curiosity/tension alone if its factual grounding
# is weak.
FACTUAL_SUPPORT_FLOOR = 40


class StoryAngleStyle(str, Enum):
    """Supported narrative framings for one story angle."""

    MYSTERY = "mystery"
    HORROR = "horror"
    INVESTIGATION = "investigation"
    CHARACTER_POV = "character_pov"
    CHRONOLOGICAL = "chronological"
    REVERSE_CHRONOLOGY = "reverse_chronology"
    REVELATION_DRIVEN = "revelation_driven"
    DOCUMENTARY = "documentary"
    EMOTIONAL = "emotional"
    QUESTION_DRIVEN = "question_driven"


class StoryAngle(MissionBaseModel):
    """
    One candidate narrative framing for a topic (spec section 21).

    Multiple candidates are generated before script writing so a
    topic is not committed to the first framing an LLM produces.
    """

    style: StoryAngleStyle
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)

    @field_validator("title", "description")
    @classmethod
    def clean_text(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Story angle text cannot be empty.")

        return cleaned


class StoryAngleEvaluation(MissionBaseModel):
    """
    Scored evaluation of one candidate StoryAngle (spec section 22).

    Matched back to its StoryAngle by title rather than id, since the
    evaluating LLM call only sees the generated angles as text - see
    StoryAngleEvaluationService for the matching logic.
    """

    angle_title: str = Field(min_length=1)

    hook_potential: int = Field(ge=0, le=100)
    curiosity: int = Field(ge=0, le=100)
    emotional_impact: int = Field(ge=0, le=100)
    originality: int = Field(ge=0, le=100)
    factual_support: int = Field(ge=0, le=100)
    clarity: int = Field(ge=0, le=100)
    tension: int = Field(ge=0, le=100)
    audience_fit: int = Field(ge=0, le=100)
    visual_potential: int = Field(ge=0, le=100)
    audio_potential: int = Field(ge=0, le=100)
    production_feasibility: int = Field(ge=0, le=100)
    payoff_potential: int = Field(ge=0, le=100)
    retention_potential: int = Field(ge=0, le=100)

    reasoning: str = Field(min_length=1)

    @property
    def overall_score(self) -> float:
        """
        Mean of all thirteen dimensions, capped at factual_support
        whenever factual_support falls below FACTUAL_SUPPORT_FLOOR -
        see the module-level constant's docstring.
        """

        dimensions = (
            self.hook_potential,
            self.curiosity,
            self.emotional_impact,
            self.originality,
            self.factual_support,
            self.clarity,
            self.tension,
            self.audience_fit,
            self.visual_potential,
            self.audio_potential,
            self.production_feasibility,
            self.payoff_potential,
            self.retention_potential,
        )

        raw_average = sum(dimensions) / len(dimensions)

        if self.factual_support < FACTUAL_SUPPORT_FLOOR:
            return min(raw_average, float(self.factual_support))

        return raw_average

    @property
    def confidence_score(self) -> float:
        """Overall score normalized to 0-1 for approval-policy escalation."""

        return self.overall_score / 100.0
