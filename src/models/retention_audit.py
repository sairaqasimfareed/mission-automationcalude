from __future__ import annotations

from enum import Enum

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel


class RetentionIssueType(str, Enum):
    """Mechanically detectable retention problem in a story blueprint."""

    INSUFFICIENT_REVEAL_DENSITY = "insufficient_reveal_density"
    REVEAL_GAP_TOO_LONG = "reveal_gap_too_long"
    LOW_TENSION_VARIATION = "low_tension_variation"


class RetentionFinding(MissionBaseModel):
    """One retention issue detected in a story blueprint, before writing."""

    issue_type: RetentionIssueType
    description: str = Field(min_length=1)
    position_seconds: float | None = Field(default=None, ge=0.0)

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Retention finding description cannot be empty.")

        return cleaned


class RetentionAuditReport(MissionBaseModel):
    """
    Result of auditing one StoryBlueprint's reveal spacing and tension
    variation against its genre's retention policy - rule-based and
    mechanical, checking positions and counts, not narrative quality
    (that judgment belongs to the editorial critics, which run after
    the script is written and can actually read the prose).
    """

    topic: str = Field(min_length=1)
    genre_id: str = Field(min_length=1)
    reveal_count: int = Field(ge=0)
    expected_minimum_reveal_count: int = Field(ge=0)
    findings: list[RetentionFinding] = Field(default_factory=list)

    @field_validator("genre_id")
    @classmethod
    def validate_genre_id(cls, value: str) -> str:
        normalized = value.strip().lower()

        if not normalized.startswith("genre."):
            raise ValueError("Genre ID must start with 'genre.'.")

        return normalized

    @property
    def passed(self) -> bool:
        """Return whether the audit found no retention issues."""

        return not self.findings
