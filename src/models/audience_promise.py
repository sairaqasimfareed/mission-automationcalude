from __future__ import annotations

from enum import Enum

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel


class PromiseStrength(str, Enum):
    """How compelling one topic's central viewer promise is."""

    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"


class AudiencePromise(MissionBaseModel):
    """
    The central viewer promise for one topic, established before
    expensive research begins (spec section 10).

    A weak promise (PromiseStrength.WEAK) signals the topic may need
    another angle, more research, or human review before continuing -
    this model only captures the assessment, it does not act on it.
    """

    topic: str = Field(min_length=1)
    target_audience: str = Field(min_length=1)
    platform: str = Field(min_length=1)
    genre_id: str = Field(min_length=1)
    target_duration_seconds: int = Field(gt=0)

    intended_emotion: str = Field(min_length=1)
    central_curiosity: str = Field(min_length=1)
    primary_question: str = Field(min_length=1)
    viewer_benefit: str = Field(min_length=1)
    expected_payoff: str = Field(min_length=1)

    promise_strength: PromiseStrength
    weakness_reasons: list[str] = Field(default_factory=list)

    prompt_version: str = Field(min_length=1)

    @field_validator("genre_id")
    @classmethod
    def validate_genre_id(cls, value: str) -> str:
        normalized = value.strip().lower()

        if not normalized.startswith("genre."):
            raise ValueError("Genre ID must start with 'genre.'.")

        return normalized

    @property
    def is_weak(self) -> bool:
        """Return whether this promise is too weak to build on as-is."""

        return self.promise_strength == PromiseStrength.WEAK

    @property
    def confidence_score(self) -> float:
        """
        Heuristic confidence signal (0-1) for approval-policy
        escalation (spec section 56): strong promises can plausibly
        auto-continue, weak ones should not.
        """

        return {
            PromiseStrength.STRONG: 0.9,
            PromiseStrength.MODERATE: 0.6,
            PromiseStrength.WEAK: 0.25,
        }[self.promise_strength]
