from __future__ import annotations

from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from src.models.base import MissionBaseModel
from src.models.enums import Platform


class SEOStatus(str, Enum):
    DRAFT = "draft"
    UNDER_REVIEW = "under_review"
    REVISION_REQUIRED = "revision_required"
    APPROVED = "approved"
    REJECTED = "rejected"


class TitleCandidate(MissionBaseModel):
    """One scored candidate title for a video."""

    text: str = Field(min_length=1, max_length=200)

    relevance_score: int = Field(default=0, ge=0, le=100)
    clarity_score: int = Field(default=0, ge=0, le=100)
    curiosity_score: int = Field(default=0, ge=0, le=100)
    specificity_score: int = Field(default=0, ge=0, le=100)
    audience_fit_score: int = Field(default=0, ge=0, le=100)
    clickbait_risk_score: int = Field(default=0, ge=0, le=100)

    selected: bool = False

    @field_validator("text")
    @classmethod
    def clean_text(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Title candidate text cannot be empty.")

        return cleaned

    @property
    def overall_score(self) -> float:
        """
        Return one composite score for ranking candidates.

        Clickbait risk is subtracted rather than averaged in, so a
        title that scores well elsewhere but reads as misleading
        still ranks lower.
        """

        positive_average = (
            self.relevance_score
            + self.clarity_score
            + self.curiosity_score
            + self.specificity_score
            + self.audience_fit_score
        ) / 5

        return round(positive_average - (self.clickbait_risk_score / 4), 2)


class SEOKeywordSet(MissionBaseModel):
    """Distinct keyword categories for one video's SEO package."""

    primary_keywords: list[str] = Field(default_factory=list)
    secondary_keywords: list[str] = Field(default_factory=list)
    long_tail_keywords: list[str] = Field(default_factory=list)

    @field_validator(
        "primary_keywords",
        "secondary_keywords",
        "long_tail_keywords",
    )
    @classmethod
    def clean_keywords(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []

        for value in values:
            normalized = value.strip().lower()

            if normalized and normalized not in cleaned:
                cleaned.append(normalized)

        return cleaned


class SEOPlatformMetadata(MissionBaseModel):
    """Platform-specific packaging metadata for one video."""

    platform: Platform
    category: str | None = None

    language: str = "English"
    language_code: str = "en"

    extra: dict[str, str] = Field(default_factory=dict)


class SEOPackage(MissionBaseModel):
    """Publish-ready SEO metadata package for one video."""

    video_job_id: UUID

    title_candidates: list[TitleCandidate] = Field(default_factory=list)
    selected_title: str | None = None

    description: str = ""
    hook_summary: str = ""

    keywords: SEOKeywordSet = Field(default_factory=SEOKeywordSet)
    tags: list[str] = Field(default_factory=list)
    hashtags: list[str] = Field(default_factory=list)

    platform_metadata: SEOPlatformMetadata

    prompt_version: str
    status: SEOStatus = SEOStatus.DRAFT

    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []

        for value in values:
            normalized = value.strip().lower()

            if normalized and normalized not in cleaned:
                cleaned.append(normalized)

        return cleaned

    @field_validator("hashtags")
    @classmethod
    def clean_hashtags(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []

        for value in values:
            normalized = value.strip().lstrip("#").lower()

            if not normalized:
                continue

            tag = f"#{normalized}"

            if tag not in cleaned:
                cleaned.append(tag)

        return cleaned

    @model_validator(mode="after")
    def validate_selected_title(self) -> SEOPackage:
        if self.selected_title is None:
            return self

        candidate_texts = {candidate.text for candidate in self.title_candidates}

        if self.selected_title not in candidate_texts:
            raise ValueError(
                "Selected title must match one of the package's title " "candidates."
            )

        return self

    @property
    def is_ready_for_export(self) -> bool:
        """Return whether this package is ready for FinalExportPackage."""

        return (
            self.status == SEOStatus.APPROVED
            and self.selected_title is not None
            and bool(self.description.strip())
        )
