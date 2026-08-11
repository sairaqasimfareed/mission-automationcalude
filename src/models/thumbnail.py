from __future__ import annotations

from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel


class ThumbnailImageSourceType(str, Enum):
    """Where a thumbnail's base image came from."""

    AI_GENERATED = "ai_generated"
    LOCAL_UPLOAD = "local_upload"
    SCENE_FRAME = "scene_frame"


class ThumbnailTextPosition(str, Enum):
    """Supported hook-text placements within a thumbnail layout."""

    TOP = "top"
    CENTER = "center"
    BOTTOM = "bottom"


class ThumbnailArtifactStatus(str, Enum):
    DRAFT = "draft"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class ThumbnailConcept(MissionBaseModel):
    """One candidate thumbnail concept: hook text plus a visual prompt."""

    concept_summary: str = Field(min_length=1, max_length=300)
    hook_text: str = Field(min_length=1, max_length=80)
    visual_prompt: str = Field(min_length=1)

    relevance_score: int = Field(default=0, ge=0, le=100)
    curiosity_score: int = Field(default=0, ge=0, le=100)
    clarity_score: int = Field(default=0, ge=0, le=100)
    text_readability_score: int = Field(default=0, ge=0, le=100)

    selected: bool = False

    @field_validator("concept_summary", "hook_text", "visual_prompt")
    @classmethod
    def clean_required_text(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Thumbnail concept text cannot be empty.")

        return cleaned

    @property
    def overall_score(self) -> float:
        """Return one composite score for ranking concepts."""

        return round(
            (
                self.relevance_score
                + self.curiosity_score
                + self.clarity_score
                + self.text_readability_score
            )
            / 4,
            2,
        )


class ThumbnailLayout(MissionBaseModel):
    """Deterministic composition rules for one thumbnail."""

    width: int = Field(gt=0)
    height: int = Field(gt=0)

    hook_text_position: ThumbnailTextPosition = ThumbnailTextPosition.BOTTOM

    hook_text_font_scale: float = Field(default=0.12, gt=0.0, le=1.0)

    safe_margin_ratio: float = Field(default=0.05, ge=0.0, lt=0.5)

    @property
    def aspect_ratio(self) -> float:
        """Return the layout's width/height ratio."""

        return self.width / self.height


class ThumbnailArtifact(MissionBaseModel):
    """One stored, publish-candidate thumbnail image."""

    video_job_id: UUID

    concept: ThumbnailConcept
    layout: ThumbnailLayout

    image_source_type: ThumbnailImageSourceType
    provider_name: str

    file_path: str
    file_size_bytes: int = Field(ge=0)
    content_hash: str | None = None

    status: ThumbnailArtifactStatus = ThumbnailArtifactStatus.DRAFT

    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("file_path", "provider_name")
    @classmethod
    def clean_required_text(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Thumbnail artifact text fields cannot be empty.")

        return cleaned

    @property
    def is_ready_for_export(self) -> bool:
        """Return whether this artifact is ready for FinalExportPackage."""

        return self.status == ThumbnailArtifactStatus.APPROVED
