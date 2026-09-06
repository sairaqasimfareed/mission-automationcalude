from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, field_validator

from src.models.approval import ApprovalDecision
from src.models.base import MissionBaseModel


class DecisionCategory(str, Enum):
    """
    Content Studio Redesign, Phase 18: what *kind* of event a
    ContentDecisionRecord represents, so an activity-history view can
    filter/label entries without inspecting the presence/absence of
    other fields as a proxy.

    Deliberately small and closed - one bucket per PDF-2 Phase 18 event
    family ("generation/review/approval/unapproval/invalidation/
    restore/lock"), with review+approval+unapproval folded into
    APPROVAL/LOCK/UNLOCK respectively since ApprovalDecision.state
    already distinguishes pending-review from resolved-approved, and
    unlocking an already-locked script is the practical meaning of
    "unapproval" in this pipeline.
    """

    GENERATION = "generation"
    APPROVAL = "approval"
    INVALIDATION = "invalidation"
    RESTORE = "restore"
    LOCK = "lock"
    UNLOCK = "unlock"


class ContentDecisionRecord(MissionBaseModel):
    """
    One immutable audit-trail entry for a content-pipeline decision.

    VideoJob's research/script/... fields are single-slot and get
    overwritten whenever a stage re-runs, so a re-run leaves no trace
    of what the previous attempt produced, which provider/model made
    it, what it cost, or how it was approved. Appending one of these
    records whenever a content stage produces or resolves something
    is what preserves that history - it does not replace the
    single-slot fields, it traces them.
    """

    stage: str
    summary: str

    provider_name: str | None = None
    model: str | None = None
    cost_usd: float | None = Field(default=None, ge=0.0)

    approval: ApprovalDecision | None = None

    category: DecisionCategory | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def effective_category(self) -> DecisionCategory:
        """
        The record's category, inferring one for records written
        before this field existed (backward-compatible: an old
        persisted job's content_decisions still classify sensibly
        instead of showing as uncategorized).
        """

        if self.category is not None:
            return self.category

        if self.approval is not None:
            return DecisionCategory.APPROVAL

        return DecisionCategory.GENERATION

    @field_validator("stage")
    @classmethod
    def clean_stage(cls, value: str) -> str:
        cleaned = value.strip().lower()

        if not cleaned:
            raise ValueError("Content decision stage cannot be empty.")

        return cleaned

    @field_validator("summary")
    @classmethod
    def clean_summary(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Content decision summary cannot be empty.")

        return cleaned
