from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator

from src.models.approval import ApprovalDecision
from src.models.base import MissionBaseModel


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

    metadata: dict[str, Any] = Field(default_factory=dict)

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
