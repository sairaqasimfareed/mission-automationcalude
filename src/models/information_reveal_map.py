from __future__ import annotations

from enum import Enum

from pydantic import Field, field_validator, model_validator

from src.models.base import MissionBaseModel

# Below this normalized story position, a resolved curiosity loop is
# flagged as prematurely resolved - it could not have sustained
# curiosity for long. Loops that genuinely need to resolve early
# (spec section 25: "allow intentional ambiguity where genre/style
# requires it") should set allow_early_resolution=True instead of
# being penalized here.
PREMATURE_RESOLUTION_THRESHOLD = 0.15


class CuriosityLoopState(str, Enum):
    """Lifecycle of one major viewer question (spec section 25)."""

    OPEN = "open"
    DEVELOPING = "developing"
    PARTIALLY_ANSWERED = "partially_answered"
    ESCALATED = "escalated"
    RESOLVED = "resolved"


class CuriosityLoop(MissionBaseModel):
    """One major viewer question tracked across the story."""

    question: str = Field(min_length=1)
    state: CuriosityLoopState = CuriosityLoopState.OPEN

    opened_at_position: float = Field(ge=0.0, le=1.0)
    resolved_at_position: float | None = Field(default=None, ge=0.0, le=1.0)

    allow_early_resolution: bool = False

    @field_validator("question")
    @classmethod
    def clean_question(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Curiosity loop question cannot be empty.")

        return cleaned

    @model_validator(mode="after")
    def validate_positions(self) -> CuriosityLoop:
        if (
            self.resolved_at_position is not None
            and self.resolved_at_position < self.opened_at_position
        ):
            raise ValueError("A curiosity loop cannot resolve before it opens.")

        if (
            self.state == CuriosityLoopState.RESOLVED
            and self.resolved_at_position is None
        ):
            raise ValueError("A resolved curiosity loop requires resolved_at_position.")

        return self


class InformationReveal(MissionBaseModel):
    """
    One piece of information revealed at a specific point in the
    story (spec section 24), used to prevent accidental early
    spoilers and to check that every payoff has a matching setup.
    """

    position: float = Field(ge=0.0, le=1.0)
    information: str = Field(min_length=1)
    escalates_story: bool = False
    is_payoff: bool = False
    related_question: str | None = None

    @field_validator("information")
    @classmethod
    def clean_information(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Information reveal text cannot be empty.")

        return cleaned

    @field_validator("related_question")
    @classmethod
    def clean_related_question(cls, value: str | None) -> str | None:
        if value is None:
            return None

        cleaned = value.strip()

        return cleaned or None


class InformationRevealMap(MissionBaseModel):
    """
    What the viewer knows and doesn't know at each point in the
    story, plus every major question being tracked (spec sections
    24-25). Built before prose generation so a script generator has
    explicit guardrails against spoiling reveals early or leaving a
    major question dangling.
    """

    topic: str = Field(min_length=1)
    curiosity_loops: list[CuriosityLoop] = Field(default_factory=list)
    reveals: list[InformationReveal] = Field(default_factory=list)
    prompt_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def require_at_least_one_loop(self) -> InformationRevealMap:
        if not self.curiosity_loops:
            raise ValueError(
                "An information reveal map requires at least one " "curiosity loop."
            )

        return self


class CuriosityLoopValidationResult(MissionBaseModel):
    """
    Result of validating one InformationRevealMap (spec section 25).

    Only mechanically checkable issues are covered here: forgotten
    questions, payoffs with no matching setup, exact-duplicate loops,
    and premature resolution. "Artificial withholding" is explicitly
    NOT checked - detecting it would require judging narrative intent
    from position data alone, which this model cannot do honestly.
    """

    forgotten_questions: list[str] = Field(default_factory=list)
    payoffs_without_setup: list[str] = Field(default_factory=list)
    redundant_loops: list[str] = Field(default_factory=list)
    prematurely_resolved: list[str] = Field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """Return whether the reveal map has no detected issues."""

        return not (
            self.forgotten_questions
            or self.payoffs_without_setup
            or self.redundant_loops
            or self.prematurely_resolved
        )
