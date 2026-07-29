from __future__ import annotations

from enum import Enum

from pydantic import Field

from src.models.base import MissionBaseModel


class OriginalityStatus(str, Enum):
    PENDING = "pending"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REVISION_REQUIRED = "revision_required"
    FAILED = "failed"


class OriginalityResult(MissionBaseModel):
    """Stores originality analysis for a generated script."""

    script_id: str

    originality_score: int = 0
    human_value_score: int = 0
    hook_strength_score: int = 0

    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)

    status: OriginalityStatus = OriginalityStatus.PENDING
