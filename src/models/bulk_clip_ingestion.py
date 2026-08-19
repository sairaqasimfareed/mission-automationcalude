from __future__ import annotations

from enum import Enum

from pydantic import Field

from src.models.base import MissionBaseModel


class BulkClipIngestionEntryStatus(str, Enum):
    """Outcome of matching and processing one file during bulk ingestion."""

    ASSIGNED = "assigned"
    FAILED_VALIDATION = "failed_validation"
    NO_MATCHING_SCENE = "no_matching_scene"


class BulkClipIngestionEntry(MissionBaseModel):
    """One file's outcome from one bulk-ingestion run."""

    file_name: str = Field(min_length=1)
    scene_number: int | None = Field(default=None, ge=1)
    status: BulkClipIngestionEntryStatus
    detail: str = Field(min_length=1)


class BulkClipIngestionResult(MissionBaseModel):
    """
    Result of one bulk-ingestion run: every file's outcome, plus which
    scenes still have no assigned clip afterward - a partial batch
    (some clips not generated yet) is expected, not an error.
    """

    entries: list[BulkClipIngestionEntry] = Field(default_factory=list)
    scenes_still_missing_a_file: list[int] = Field(default_factory=list)

    @property
    def assigned_count(self) -> int:
        return sum(
            1
            for entry in self.entries
            if entry.status == BulkClipIngestionEntryStatus.ASSIGNED
        )

    @property
    def failed_count(self) -> int:
        return sum(
            1
            for entry in self.entries
            if entry.status
            in (
                BulkClipIngestionEntryStatus.FAILED_VALIDATION,
                BulkClipIngestionEntryStatus.NO_MATCHING_SCENE,
            )
        )
