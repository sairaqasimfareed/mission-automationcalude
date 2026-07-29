from __future__ import annotations

from enum import Enum

from pydantic import Field

from src.models.base import MissionBaseModel


class ResearchStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    UNDER_REVIEW = "under_review"
    REVISION_REQUIRED = "revision_required"
    APPROVED = "approved"
    BLOCKED = "blocked"
    FAILED = "failed"


class ResearchSource(MissionBaseModel):
    """A source used during topic research."""

    title: str
    url: str | None = None
    publisher: str | None = None
    notes: str | None = None
    confidence_score: int = 0


class ResearchResult(MissionBaseModel):
    """Structured research package used by the Script Agent."""

    topic: str
    research_summary: str

    key_facts: list[str] = Field(default_factory=list)
    interesting_angles: list[str] = Field(default_factory=list)
    potential_hooks: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)

    sources: list[ResearchSource] = Field(default_factory=list)

    fact_confidence_score: int = 0

    prompt_version: str
    status: ResearchStatus = ResearchStatus.PENDING

    claude_review_notes: list[str] = Field(default_factory=list)
    claude_suggested_changes: list[str] = Field(default_factory=list)