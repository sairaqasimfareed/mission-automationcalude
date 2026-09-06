from __future__ import annotations

from pydantic import Field

from src.models.base import MissionBaseModel


class AutomationStatus(MissionBaseModel):
    """
    Content Studio Redesign, Phase 17: "Visible current operation and
    completed stages" / "Pause reason and next required user action."

    A computed snapshot of where automation currently stands for one
    project - pure read of already-persisted job state, never itself
    persisted (recomputed fresh on every call, the same convention
    ScriptQualityReport/ScriptProductionReadinessReport already
    follow). Reflects exactly what ContentIntelligencePipeline.run_all()
    would do next; it does not decide anything on its own.
    """

    completed_stages: list[str] = Field(default_factory=list)
    pending_decision_point: str | None = None
    pending_stage: str | None = None
    pending_summary: str | None = None

    @property
    def is_paused(self) -> bool:
        return self.pending_decision_point is not None

    @property
    def is_complete(self) -> bool:
        return not self.is_paused and "scene_planning" in self.completed_stages
