from __future__ import annotations

from enum import Enum

from pydantic import Field

from src.models.base import MissionBaseModel
from src.models.blocker import Blocker, BlockerSeverity


class ReadinessState(str, Enum):
    """Overall production readiness for one project."""

    BLOCKED = "blocked"
    READY_FOR_RENDER = "ready_for_render"
    READY_FOR_FINAL_EXPORT = "ready_for_final_export"
    COMPLETED = "completed"


class ProductionReadinessReport(MissionBaseModel):
    """
    Result of evaluating one VideoJob's current readiness - the single
    answer every GUI readiness indicator should consume instead of
    re-deriving its own notion of "ready" from scattered VideoJob
    fields.
    """

    state: ReadinessState
    blockers: list[Blocker] = Field(default_factory=list)

    @property
    def blocking_issues(self) -> list[Blocker]:
        return [
            blocker
            for blocker in self.blockers
            if blocker.severity == BlockerSeverity.BLOCKING
        ]

    @property
    def is_blocked(self) -> bool:
        return self.state == ReadinessState.BLOCKED
