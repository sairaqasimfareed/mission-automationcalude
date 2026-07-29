from __future__ import annotations

from src.models.asset_state import (
    AssetWorkflowStatus,
    SceneAssetState,
)
from src.models.scene import Scene
from src.services.local_asset_search_service import (
    LocalAssetSearchService,
)


class AssetManager:
    """Manages the local-first visual asset workflow."""

    def __init__(
        self,
        local_search_service: LocalAssetSearchService,
    ) -> None:
        self.local_search_service = local_search_service

    def search_local_assets(
        self,
        scene: Scene,
    ) -> SceneAssetState:
        state = SceneAssetState(
            scene_id=str(scene.id),
            scene_number=scene.scene_number,
            status=AssetWorkflowStatus.SEARCHING_LOCAL,
            local_search_query=scene.visual_prompt,
        )

        candidates = self.local_search_service.search_for_scene(scene)

        state.local_candidates = candidates

        if candidates:
            state.status = AssetWorkflowStatus.LOCAL_RESULTS_AVAILABLE
        else:
            state.status = AssetWorkflowStatus.WAITING_FOR_USER_DECISION
            state.warnings.append("No matching local video assets were found.")

        return state
