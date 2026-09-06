from __future__ import annotations

from src.models.cinematic_prompt import CinematicPromptPackage
from src.models.clip_materialization import ClipMaterializationStatus
from src.models.media_strategy import SceneSourceStatus
from src.models.scene import Scene
from src.models.script_lock import ScriptLock


class ClipMaterializationService:
    """
    Post-Script-Approval Production Plan, Phase 5: "Calculate planned
    duration, coverage, delta and readiness from canonical timing."

    Pure aggregation, no LLM call - every input is already-persisted
    Scene/CinematicPromptPackage state. Reused directly rather than
    re-derived: Scene.source_status/source_type/estimated_cost/
    estimated_duration_seconds (the existing Clip Workspace's own
    routing/readiness fields) and Scene.locked_script_hash (Phase 0's
    downstream-hash stamp).
    """

    @staticmethod
    def compute(
        *,
        scenes: list[Scene],
        script_lock: ScriptLock | None,
        cinematic_prompt_package: CinematicPromptPackage | None,
        target_duration_seconds: float,
    ) -> ClipMaterializationStatus:
        ready_clips = sum(
            1 for scene in scenes if scene.source_status == SceneSourceStatus.READY
        )

        stale_clips = (
            sum(
                1
                for scene in scenes
                if scene.locked_script_hash != script_lock.script_content_hash
            )
            if script_lock is not None
            else 0
        )

        traced_to_prompt_clips = (
            sum(
                1
                for scene in scenes
                if cinematic_prompt_package.prompt_for_scene(scene.scene_number)
                is not None
            )
            if cinematic_prompt_package is not None
            else 0
        )

        route_counts: dict[str, int] = {}
        for scene in scenes:
            route_counts[scene.source_type.value] = (
                route_counts.get(scene.source_type.value, 0) + 1
            )

        return ClipMaterializationStatus(
            total_clips=len(scenes),
            ready_clips=ready_clips,
            missing_clips=len(scenes) - ready_clips,
            stale_clips=stale_clips,
            traced_to_prompt_clips=traced_to_prompt_clips,
            route_counts=route_counts,
            planned_duration_seconds=sum(
                scene.estimated_duration_seconds for scene in scenes
            ),
            target_duration_seconds=target_duration_seconds,
            total_estimated_cost=sum(scene.estimated_cost for scene in scenes),
        )
