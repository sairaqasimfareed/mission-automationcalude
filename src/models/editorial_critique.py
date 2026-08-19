from __future__ import annotations

from enum import Enum

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel


class QualityDimension(str, Enum):
    """
    Canonical quality dimension vocabulary the editorial critique
    scores against. These are the same dimension names genre profiles
    use as keys in GenreContentIntelligenceProfile.quality_thresholds
    (Sprint A1) - the critique scores every dimension in this set, and
    ScriptQualityGateService only gates on whichever subset a given
    genre actually declares a threshold for.
    """

    FACTUAL_CONFIDENCE = "factual_confidence"
    HOOK_STRENGTH = "hook_strength"
    RETENTION_ARCHITECTURE = "retention_architecture"
    EMOTIONAL_PROGRESSION = "emotional_progression"
    RESEARCH_GROUNDING = "research_grounding"
    NARRATIVE_COHERENCE = "narrative_coherence"
    AUDIENCE_FIT = "audience_fit"
    VISUAL_OPPORTUNITY_DENSITY = "visual_opportunity_density"
    CHARACTER_DEPTH = "character_depth"
    PAYOFF_STRENGTH = "payoff_strength"
    CONTINUITY = "continuity"


# Scored only when a genre's character_policy is set - informational
# genres (documentary, top10, medical) skip these entirely rather than
# being scored on an axis their content has no use for.
CHARACTER_DEPENDENT_DIMENSIONS = frozenset(
    {QualityDimension.CHARACTER_DEPTH, QualityDimension.PAYOFF_STRENGTH}
)

_VALID_DIMENSION_VALUES = {dimension.value for dimension in QualityDimension}


class FindingSeverity(str, Enum):
    """How serious one critic finding is."""

    MINOR = "minor"
    MODERATE = "moderate"
    MAJOR = "major"
    BLOCKING = "blocking"


class CriticFinding(MissionBaseModel):
    """
    One specific, actionable problem raised by an editorial critic.
    Findings are always concrete (a problem, why it matters, and a
    recommended correction) - never vague "improve this" prose, so
    ScriptRevisionService has something targeted to act on.
    """

    dimension: QualityDimension
    severity: FindingSeverity
    segment_number: int | None = Field(default=None, ge=1)
    problem: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    recommended_correction: str = Field(min_length=1)

    @field_validator("problem", "reason", "recommended_correction")
    @classmethod
    def clean_text(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Critic finding text cannot be empty.")

        return cleaned


class EditorialCritique(MissionBaseModel):
    """
    Structured output of one editorial critique pass over a generated
    script - writing and evaluation are deliberately separate passes,
    the same discipline sprint 6/7's hook and angle evaluators follow.
    """

    topic: str = Field(min_length=1)
    dimension_scores: dict[str, int] = Field(default_factory=dict)
    findings: list[CriticFinding] = Field(default_factory=list)
    prompt_version: str = Field(min_length=1)

    @field_validator("dimension_scores")
    @classmethod
    def validate_dimension_scores(cls, values: dict[str, int]) -> dict[str, int]:
        for dimension, score in values.items():
            if dimension not in _VALID_DIMENSION_VALUES:
                raise ValueError(f"'{dimension}' is not a supported quality dimension.")

            if not 0 <= score <= 100:
                raise ValueError(
                    f"Quality score for '{dimension}' must be between 0 and 100."
                )

        return values

    @property
    def blocking_findings(self) -> list[CriticFinding]:
        """Findings severe enough to force revision regardless of scores."""

        return [
            finding
            for finding in self.findings
            if finding.severity == FindingSeverity.BLOCKING
        ]

    @property
    def major_findings(self) -> list[CriticFinding]:
        """Findings serious enough to warrant human editorial review."""

        return [
            finding
            for finding in self.findings
            if finding.severity == FindingSeverity.MAJOR
        ]
