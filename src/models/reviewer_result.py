from __future__ import annotations

from pydantic import Field, field_validator

from src.models.artifact_lifecycle import ArtifactType
from src.models.base import MissionBaseModel
from src.models.editorial_critique import FindingSeverity


class ReviewerIssue(MissionBaseModel):
    """
    One specific problem the Reviewer LLM raised about an artifact -
    generic across every artifact type, unlike CriticFinding (which is
    tied to the 11 fixed QualityDimension axes scripts are scored on).
    Reuses FindingSeverity since MINOR/MODERATE/MAJOR/BLOCKING is
    already a generic severity vocabulary, not script-specific.
    """

    description: str = Field(min_length=1)
    severity: FindingSeverity
    recommendation: str | None = None

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Reviewer issue description cannot be empty.")

        return cleaned

    @field_validator("recommendation")
    @classmethod
    def clean_recommendation(cls, value: str | None) -> str | None:
        if value is None:
            return None

        cleaned = value.strip()

        return cleaned or None


class ReviewerResult(MissionBaseModel):
    """
    Structured output of one Reviewer LLM pass over one artifact
    version (Content Studio Redesign, Phase 4). The Reviewer critiques;
    it never independently authors an alternative - this model has no
    field for "here's a rewritten version", only strengths/issues/a
    suggested *direction* for revision, matching "Reviewer reviews
    Primary output on demand or at configured gates; it does not
    independently become the author."
    """

    artifact_type: ArtifactType
    reviewer_profile_id: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)

    strengths: list[str] = Field(default_factory=list)
    issues: list[ReviewerIssue] = Field(default_factory=list)
    suggested_revision_direction: str | None = None

    @field_validator("strengths")
    @classmethod
    def clean_strengths(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []

        for value in values:
            trimmed = value.strip()

            if trimmed and trimmed not in cleaned:
                cleaned.append(trimmed)

        return cleaned

    @field_validator("suggested_revision_direction")
    @classmethod
    def clean_suggested_revision_direction(cls, value: str | None) -> str | None:
        if value is None:
            return None

        cleaned = value.strip()

        return cleaned or None

    @property
    def has_blocking_issues(self) -> bool:
        return any(issue.severity == FindingSeverity.BLOCKING for issue in self.issues)
