from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import Field

from src.models.base import MissionBaseModel
from src.models.research_evidence import ManualResearchEdit, ResearchFact


class ResearchStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    UNDER_REVIEW = "under_review"
    REVISION_REQUIRED = "revision_required"
    APPROVED = "approved"
    BLOCKED = "blocked"
    FAILED = "failed"


class SourceStatus(str, Enum):
    """
    Whether one research source is currently in use (Content Studio
    Redesign, Phase 8). REJECTED sources stay in ResearchResult.sources
    rather than being removed - "User can add/reject sources without
    deleting audit history" - so rejecting a source is a status change,
    never a deletion.
    """

    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ResearchSource(MissionBaseModel):
    """A source used during topic research."""

    title: str
    url: str | None = None
    publisher: str | None = None
    notes: str | None = None
    confidence_score: int = 0

    # Content Studio Redesign, Phase 8 additions - all optional/
    # default-populated so an old ResearchSource JSON loads unchanged.
    date: str | None = None
    retrieved_at: datetime | None = None
    status: SourceStatus = SourceStatus.ACCEPTED


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

    # Content Studio Redesign, Phase 8 additions. structured_facts is
    # kept alongside key_facts above rather than replacing it -
    # key_facts is a flat list of strings read by several existing
    # production services (ScriptAgent, ScriptGenerationService, SEO
    # context/keyword generation, StoryAngleGenerationService) and
    # every one of them keeps working unmodified; structured_facts is
    # the new evidence-bound registry the Evidence Ledger GUI operates
    # on and that downstream Story Development can reference by stable
    # Fact ID (this phase's own exit criterion).
    structured_facts: list[ResearchFact] = Field(default_factory=list)
    research_gaps: list[str] = Field(default_factory=list)
    manual_edits: list[ManualResearchEdit] = Field(default_factory=list)
