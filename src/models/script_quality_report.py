from __future__ import annotations

from enum import Enum

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel
from src.models.editorial_critique import CriticFinding


class ScriptQualityStatus(str, Enum):
    """
    Editorial lifecycle status of one generated script.

    DRAFT is the implicit pre-evaluation state (no ScriptQualityReport
    exists yet for the script) - ScriptQualityGateService.evaluate()
    never returns it, only the three post-evaluation outcomes below.
    """

    DRAFT = "draft"
    NEEDS_REVISION = "needs_revision"
    EDITORIAL_REVIEW = "editorial_review"
    APPROVED_FOR_PRODUCTION = "approved_for_production"


class ScriptQualityReport(MissionBaseModel):
    """
    Aggregation of one EditorialCritique against its genre's quality
    thresholds (spec: quality gates, not vibes). Pure aggregation -
    every score and finding here was produced upstream by the
    critique pass; this model and its producing service never invent
    a score of their own.
    """

    topic: str = Field(min_length=1)
    genre_id: str = Field(min_length=1)

    dimension_scores: dict[str, int] = Field(default_factory=dict)
    dimension_thresholds: dict[str, int] = Field(default_factory=dict)
    failed_dimensions: list[str] = Field(default_factory=list)

    blocking_findings: list[CriticFinding] = Field(default_factory=list)
    major_findings: list[CriticFinding] = Field(default_factory=list)

    status: ScriptQualityStatus

    @field_validator("genre_id")
    @classmethod
    def validate_genre_id(cls, value: str) -> str:
        normalized = value.strip().lower()

        if not normalized.startswith("genre."):
            raise ValueError("Genre ID must start with 'genre.'.")

        return normalized

    @property
    def passed(self) -> bool:
        """Return whether this script is approved for production."""

        return self.status == ScriptQualityStatus.APPROVED_FOR_PRODUCTION
