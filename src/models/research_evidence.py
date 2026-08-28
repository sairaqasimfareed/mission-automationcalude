from __future__ import annotations

from enum import Enum
from uuid import UUID

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel


class EvidenceSupportType(str, Enum):
    """How directly one piece of evidence supports the fact it's attached to."""

    DIRECT = "direct"
    INFERRED = "inferred"
    CONTEXTUAL = "contextual"


class ContradictionStatus(str, Enum):
    """Whether a fact's evidence has an unresolved conflict across sources."""

    NONE = "none"
    FLAGGED = "flagged"
    RESOLVED = "resolved"


class EvidenceRecord(MissionBaseModel):
    """
    One binding between a fact and the source that supports it (Content
    Studio Redesign, Phase 8: Research Execution, Evidence Ledger and
    Fact Integrity).

    `source_id` references a ResearchSource.id rather than duplicating
    the source's own fields here - a source's title/url/publisher stay
    editable (or rejectable) in exactly one place.
    """

    source_id: UUID
    passage: str | None = None
    confidence: int = Field(ge=0, le=100)
    support_type: EvidenceSupportType
    contradiction_status: ContradictionStatus = ContradictionStatus.NONE

    @field_validator("passage")
    @classmethod
    def clean_passage(cls, value: str | None) -> str | None:
        if value is None:
            return None

        cleaned = value.strip()

        return cleaned or None


class ResearchFact(MissionBaseModel):
    """
    One verifiable claim bound to one or more supporting EvidenceRecord
    entries - the "Claim IDs and Fact IDs bind synthesized claims to
    one or more supporting sources/passages" requirement.

    This model deliberately serves as both "claim" and "fact" from the
    spec's own wording, rather than a two-stage claim-then-fact
    promotion pipeline: `id` (inherited from MissionBaseModel) is a
    stable identifier from the moment a claim is synthesized, and
    stays that same identifier once evidence-bound - there's no
    separate promotion step that would require reconciling two
    different ID spaces. A fact with `evidence=[]` is an unsupported
    claim, still trackable and reviewable by its own id.
    """

    text: str = Field(min_length=1)
    evidence: list[EvidenceRecord] = Field(default_factory=list)

    @field_validator("text")
    @classmethod
    def clean_text(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Research fact text cannot be empty.")

        return cleaned

    @property
    def is_supported(self) -> bool:
        """Return whether this fact has at least one evidence binding."""

        return len(self.evidence) > 0


class FactCheckResult(MissionBaseModel):
    """
    Result of one FactCheckService.check() call against a manual
    research edit or any other unverified claim text - "Fact-check-
    again can re-evaluate claim support."
    """

    claim_text: str = Field(min_length=1)
    is_supported: bool
    confidence: int = Field(ge=0, le=100)
    matched_source_ids: list[UUID] = Field(default_factory=list)
    reasoning: str = Field(min_length=1)


class ManualResearchEdit(MissionBaseModel):
    """
    Text a human added or edited directly, distinct from LLM-synthesized
    ResearchFact entries - "Manual research edits do not automatically
    become verified facts." `is_verified` only ever becomes True via an
    explicit fact-check pass (FactCheckService), never automatically on
    creation or edit.
    """

    text: str = Field(min_length=1)
    is_verified: bool = False
    verification_notes: str | None = None

    @field_validator("text")
    @classmethod
    def clean_text(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Manual research edit text cannot be empty.")

        return cleaned

    @field_validator("verification_notes")
    @classmethod
    def clean_verification_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None

        cleaned = value.strip()

        return cleaned or None
