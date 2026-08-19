from __future__ import annotations

from enum import Enum

from pydantic import Field

from src.models.base import MissionBaseModel


class BulkStockAssignmentEntryStatus(str, Enum):
    """Outcome of assigning stock footage to one scene during a bulk run."""

    ASSIGNED = "assigned"
    FAILED = "failed"


class BulkStockAssignmentEntry(MissionBaseModel):
    """One scene's outcome from one bulk stock-assignment run."""

    scene_number: int = Field(ge=1)
    status: BulkStockAssignmentEntryStatus
    detail: str = Field(min_length=1)


class BulkStockAssignmentResult(MissionBaseModel):
    """Result of one bulk stock-assignment run across many scenes."""

    entries: list[BulkStockAssignmentEntry] = Field(default_factory=list)

    @property
    def assigned_count(self) -> int:
        return sum(
            1
            for entry in self.entries
            if entry.status == BulkStockAssignmentEntryStatus.ASSIGNED
        )

    @property
    def failed_count(self) -> int:
        return sum(
            1
            for entry in self.entries
            if entry.status == BulkStockAssignmentEntryStatus.FAILED
        )
