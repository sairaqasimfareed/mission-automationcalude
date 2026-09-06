from __future__ import annotations

from enum import Enum

from src.models.base import MissionBaseModel


class ProductionHandoffState(str, Enum):
    """
    Post-Script-Approval Production Plan, Phase 0: "Emit a post-
    approval production state such as LOCKED / BUILDING_PACKAGE /
    PACKAGE_READY / BLOCKED."
    """

    BLOCKED = "blocked"
    LOCKED = "locked"
    BUILDING_PACKAGE = "building_package"
    PACKAGE_READY = "package_ready"


class ProductionHandoffStatus(MissionBaseModel):
    """
    A computed snapshot of where the post-approval production package
    stands for one project - pure read of already-persisted job
    state, never itself persisted (recomputed fresh on every call,
    the same convention AutomationStatus/ScriptQualityReport already
    follow).

    "Approved script becomes a canonical production source of truth"
    (Phase 0's objective) means downstream production planning
    (scene/clip materialization) should never run against an
    unlocked or hash-stale script - this status is what a GUI reads
    to decide whether to show "Script locked for production," a
    build-in-progress state, package-ready readiness, or a blocker,
    without re-deriving that logic itself.
    """

    state: ProductionHandoffState
    blocked_reason: str | None = None
    locked_script_hash: str | None = None

    @property
    def is_ready(self) -> bool:
        return self.state == ProductionHandoffState.PACKAGE_READY
