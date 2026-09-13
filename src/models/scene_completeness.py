from __future__ import annotations

from enum import Enum

from pydantic import Field

from src.models.base import MissionBaseModel


class SceneCompletenessStatus(str, Enum):
    """
    One scene's real, verified readiness for final render.

    Deliberately code-only/deterministic - this checks facts already
    on the job (ledger state, a downloaded file's real existence,
    whether video_clips actually has an entry), never an LLM judgment
    call. Visual continuity across scenes is explicitly out of scope
    (a human review decision per this project), this is only "did the
    mechanical pipeline actually finish for every scene."
    """

    READY = "ready"
    IN_PROGRESS = "in_progress"
    NEEDS_ATTENTION = "needs_attention"
    NOT_STARTED = "not_started"


class SceneCompletenessEntry(MissionBaseModel):
    """One scene's completeness verdict, with the three real checkpoints."""

    scene_number: int = Field(ge=1)

    status: SceneCompletenessStatus

    # Real-world finding, 2026-09: Google Flow's own "downloaded"
    # toast lied - only 1 of 4 files it reported as downloaded had
    # actually landed on disk. These three booleans are independently
    # meaningful precisely because they can disagree with what a
    # provider claims.
    generated: bool
    downloaded: bool
    attached: bool

    detail: str


class SceneCompletenessReport(MissionBaseModel):
    """Every scene's completeness verdict for one job."""

    entries: list[SceneCompletenessEntry] = Field(default_factory=list)

    @property
    def all_ready(self) -> bool:
        return bool(self.entries) and all(
            entry.status == SceneCompletenessStatus.READY for entry in self.entries
        )

    @property
    def scenes_needing_attention(self) -> list[SceneCompletenessEntry]:
        return [
            entry
            for entry in self.entries
            if entry.status == SceneCompletenessStatus.NEEDS_ATTENTION
        ]

    @property
    def scenes_in_progress(self) -> list[SceneCompletenessEntry]:
        return [
            entry
            for entry in self.entries
            if entry.status == SceneCompletenessStatus.IN_PROGRESS
        ]
