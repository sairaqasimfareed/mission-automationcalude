from datetime import datetime
from enum import Enum

from pydantic import Field

from src.models.base import MissionBaseModel


class ScriptStatus(str, Enum):
    DRAFT = "draft"
    UNDER_REVIEW = "under_review"
    REVISION_REQUIRED = "revision_required"
    APPROVED = "approved"
    REJECTED = "rejected"


class ScriptReviewStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REVISION_REQUIRED = "revision_required"
    REJECTED = "rejected"
    BLOCKED = "blocked"


class Script(MissionBaseModel):
    """A versioned video script with Claude review metadata."""

    title: str
    content: str

    prompt_version: str
    script_version: str = "1.0.0"

    word_count: int = 0
    estimated_duration_seconds: int = 0

    status: ScriptStatus = ScriptStatus.DRAFT

    claude_review_status: ScriptReviewStatus = ScriptReviewStatus.PENDING
    claude_review_notes: list[str] = Field(default_factory=list)
    claude_suggested_changes: list[str] = Field(default_factory=list)
    claude_reviewed_at: datetime | None = None

    revision_count: int = 0
