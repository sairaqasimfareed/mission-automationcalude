from __future__ import annotations

from enum import Enum

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel

# Same rationale as StoryAngleEvaluation.overall_score's
# FACTUAL_SUPPORT_FLOOR (spec's running "factual integrity overrides
# engagement" principle, section 79) applied to hooks.
FACTUAL_SUPPORT_FLOOR = 40


class HookRejectionReason(str, Enum):
    """Why one hook candidate was rejected outright (spec section 28)."""

    MISLEADING_CLICKBAIT = "misleading_clickbait"
    UNSUPPORTED_CLAIM = "unsupported_claim"
    GENERIC_INTRODUCTION = "generic_introduction"
    UNNECESSARY_GREETING = "unnecessary_greeting"
    SLOW_SETUP = "slow_setup"
    COMPLETE_SPOILER = "complete_spoiler"


class HookCandidate(MissionBaseModel):
    """One candidate opening hook for a video."""

    text: str = Field(min_length=1, max_length=400)

    @field_validator("text")
    @classmethod
    def clean_text(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Hook text cannot be empty.")

        return cleaned


class HookEvaluation(MissionBaseModel):
    """
    Scored evaluation of one HookCandidate (spec section 29).

    Matched back to its candidate by text, the same pattern
    StoryAngleEvaluation uses for angle titles.
    """

    hook_text: str = Field(min_length=1)

    immediate_curiosity: int = Field(ge=0, le=100)
    specificity: int = Field(ge=0, le=100)
    stakes: int = Field(ge=0, le=100)
    clarity: int = Field(ge=0, le=100)
    emotional_impact: int = Field(ge=0, le=100)
    novelty: int = Field(ge=0, le=100)
    relevance: int = Field(ge=0, le=100)
    audience_fit: int = Field(ge=0, le=100)
    factual_support: int = Field(ge=0, le=100)
    spoiler_risk: int = Field(ge=0, le=100)

    rejected: bool = False
    rejection_reasons: list[HookRejectionReason] = Field(default_factory=list)

    reasoning: str = Field(min_length=1)

    @property
    def overall_score(self) -> float:
        """
        Mean of the nine positive dimensions, penalized by
        spoiler_risk and capped at factual_support when that falls
        below FACTUAL_SUPPORT_FLOOR - see StoryAngleEvaluation's
        equivalent property for the same reasoning. A rejected hook
        always scores 0 regardless of its dimension scores, since
        spec section 28 requires outright rejection, not merely a
        low score, for clickbait/unsupported/spoiler hooks.
        """

        if self.rejected:
            return 0.0

        positive_dimensions = (
            self.immediate_curiosity,
            self.specificity,
            self.stakes,
            self.clarity,
            self.emotional_impact,
            self.novelty,
            self.relevance,
            self.audience_fit,
            self.factual_support,
        )

        raw_average = sum(positive_dimensions) / len(positive_dimensions)
        penalized = max(0.0, raw_average - self.spoiler_risk)

        if self.factual_support < FACTUAL_SUPPORT_FLOOR:
            return min(penalized, float(self.factual_support))

        return penalized

    @property
    def confidence_score(self) -> float:
        """Overall score normalized to 0-1 for approval-policy escalation."""

        return self.overall_score / 100.0
