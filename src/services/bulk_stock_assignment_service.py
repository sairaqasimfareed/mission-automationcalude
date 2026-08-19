from __future__ import annotations

from src.models.asset_state import AssetUserDecision, SceneAssetState
from src.models.bulk_stock_assignment import (
    BulkStockAssignmentEntry,
    BulkStockAssignmentEntryStatus,
    BulkStockAssignmentResult,
)
from src.models.scene import Scene
from src.models.video_job import VideoJob
from src.services.scene_asset_video_clip_builder_service import (
    SceneAssetVideoClipBuilderService,
)
from src.services.scene_asset_workflow_service import SceneAssetWorkflowService


class BulkStockAssignmentService:
    """
    Searches and auto-selects the top-ranked stock footage candidate
    for many scenes at once, through the real stock workflow -
    SceneAssetWorkflowService.search_stock() then .apply_decision()
    with the first result, the exact same calls the Render Workspace
    GUI makes one scene at a time. Bulk mode only removes the human
    candidate-review step (impractical across dozens of scenes); it
    does not reimplement search, ranking, or acquisition.
    """

    def __init__(
        self,
        *,
        asset_workflow_service: SceneAssetWorkflowService,
        video_clip_builder_service: SceneAssetVideoClipBuilderService | None = None,
    ) -> None:
        self.asset_workflow_service = asset_workflow_service
        self.video_clip_builder_service = (
            video_clip_builder_service or SceneAssetVideoClipBuilderService()
        )

    def assign(
        self, *, job: VideoJob, scene_numbers: list[int]
    ) -> BulkStockAssignmentResult:
        if not scene_numbers:
            raise ValueError(
                "At least one scene number is required for bulk stock assignment."
            )

        scenes_by_number = {scene.scene_number: scene for scene in job.scenes}
        states_by_number = {
            state.scene_number: state for state in job.scene_asset_states
        }

        entries = [
            self._assign_one(
                scene_number,
                job=job,
                scenes_by_number=scenes_by_number,
                states_by_number=states_by_number,
            )
            for scene_number in scene_numbers
        ]

        job.scene_asset_states = list(states_by_number.values())
        job.video_clips = self.video_clip_builder_service.build_clips(
            scenes=job.scenes, states=job.scene_asset_states
        )

        return BulkStockAssignmentResult(entries=entries)

    def _assign_one(
        self,
        scene_number: int,
        *,
        job: VideoJob,
        scenes_by_number: dict[int, Scene],
        states_by_number: dict[int, SceneAssetState],
    ) -> BulkStockAssignmentEntry:
        scene = scenes_by_number.get(scene_number)

        if scene is None:
            return BulkStockAssignmentEntry(
                scene_number=scene_number,
                status=BulkStockAssignmentEntryStatus.FAILED,
                detail=f"No scene {scene_number} in this project.",
            )

        if scene.source_locked:
            return BulkStockAssignmentEntry(
                scene_number=scene_number,
                status=BulkStockAssignmentEntryStatus.FAILED,
                detail=f"Scene {scene_number} is locked - unlock it before reassigning.",
            )

        state = states_by_number.get(scene_number) or self.asset_workflow_service.start(
            scene
        )
        searched_state = self.asset_workflow_service.search_stock(
            scene=scene, state=state
        )
        states_by_number[scene_number] = searched_state

        if (
            searched_state.active_failure is not None
            or not searched_state.stock_candidates
        ):
            detail = (
                searched_state.active_failure.message
                if searched_state.active_failure is not None
                else "No stock footage candidates were found."
            )

            return BulkStockAssignmentEntry(
                scene_number=scene_number,
                status=BulkStockAssignmentEntryStatus.FAILED,
                detail=detail,
            )

        updated_state = self.asset_workflow_service.apply_decision(
            scene=scene,
            state=searched_state,
            decision=AssetUserDecision.USE_STOCK,
            selected_candidate_index=0,
            project_id=job.project_name,
        )
        states_by_number[scene_number] = updated_state

        if not updated_state.is_ready:
            detail = (
                updated_state.active_failure.message
                if updated_state.active_failure is not None
                else "Stock footage could not be acquired."
            )

            return BulkStockAssignmentEntry(
                scene_number=scene_number,
                status=BulkStockAssignmentEntryStatus.FAILED,
                detail=detail,
            )

        return BulkStockAssignmentEntry(
            scene_number=scene_number,
            status=BulkStockAssignmentEntryStatus.ASSIGNED,
            detail=f"Assigned to scene {scene_number}.",
        )
