from __future__ import annotations

from pydantic import Field

from src.models.base import MissionBaseModel


class ClipMaterializationStatus(MissionBaseModel):
    """
    Post-Script-Approval Production Plan, Phase 5: "Populate Clip
    Workspace automatically from the canonical post-lock package" -
    the top summary a GUI reads: "total/ready/missing, route counts,
    duration integrity and estimated generation budget."

    Pure aggregation over already-persisted state (Scene's own
    source_status/source_type/estimated_cost/estimated_duration_seconds,
    already extended in Phase 0 with locked_script_hash, plus whether
    each scene has a resolved prompt) - no LLM call, no invented
    score, the same convention ScriptProductionReadinessReport already
    follows.

    REUSE note: this codebase already has a real "Clip Workspace" -
    Scene itself, materialized automatically by
    ContentIntelligencePipeline.run_scene_planning() with routing
    (source_type/source_status/fallback_sources) and asset-acquisition
    state (SceneAssetState) already built. "No manual Plan Clips step"
    and "workspace is a projection, not a parallel planner" already
    hold by construction - this status model is the one genuinely
    missing piece: a single readiness summary over that existing
    workspace, tracing lock -> semantic -> continuity -> shot ->
    prompt via the one stable id every one of those artifacts already
    shares, Scene.scene_number.
    """

    total_clips: int = Field(ge=0)
    ready_clips: int = Field(ge=0)
    missing_clips: int = Field(ge=0)
    stale_clips: int = Field(ge=0)
    traced_to_prompt_clips: int = Field(ge=0)

    route_counts: dict[str, int] = Field(default_factory=dict)

    planned_duration_seconds: float = Field(ge=0.0)
    target_duration_seconds: float = Field(ge=0.0)
    total_estimated_cost: float = Field(ge=0.0)

    @property
    def duration_delta_seconds(self) -> float:
        return self.planned_duration_seconds - self.target_duration_seconds

    @property
    def is_fully_traced(self) -> bool:
        """
        "Every clip traces lock -> semantic -> continuity -> shot ->
        prompt" - this phase's own named exit criterion, checked
        mechanically rather than assumed.
        """

        return self.total_clips > 0 and self.traced_to_prompt_clips == self.total_clips

    @property
    def is_ready_for_fulfillment(self) -> bool:
        return (
            self.total_clips > 0 and self.missing_clips == 0 and self.stale_clips == 0
        )
