from __future__ import annotations

from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel
from src.models.seo import SEOPackage
from src.models.thumbnail import ThumbnailArtifact


class FinalExportStatus(str, Enum):
    DRAFT = "draft"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class FinalExportPackage(MissionBaseModel):
    """
    One publish-ready export package for a completed video.

    This is where Sprint 22 (SEOPackage) and Sprint 23
    (ThumbnailArtifact) meet the render output. It embeds the full
    SEOPackage and ThumbnailArtifact rather than flattening their
    fields - selected_title, description, keywords, tags and hashtags
    remain accessible through seo_package, matching how
    RenderOrchestrationResult embeds the full VideoJob rather than
    duplicating its fields.
    """

    video_job_id: UUID
    project_id: str

    final_video_path: str
    resolution: str
    frame_rate: int
    duration_seconds: int = Field(ge=0)

    seo_package: SEOPackage
    thumbnail_artifact: ThumbnailArtifact

    export_directory: str
    manifest_path: str | None = None

    status: FinalExportStatus = FinalExportStatus.DRAFT

    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "project_id",
        "final_video_path",
        "resolution",
        "export_directory",
    )
    @classmethod
    def clean_required_text(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Final export package text fields cannot be empty.")

        return cleaned

    @property
    def is_ready_for_publish(self) -> bool:
        """Return whether this package is approved and ready to hand off."""

        return (
            self.status == FinalExportStatus.APPROVED
            and self.seo_package.is_ready_for_export
            and self.thumbnail_artifact.is_ready_for_export
        )
