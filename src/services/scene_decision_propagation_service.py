from __future__ import annotations

from src.models.asset_state import (
    AssetUserDecision,
    AssetWorkflowStatus,
    SceneAssetState,
)
from src.models.media_strategy import SceneSourceType


class SceneDecisionPropagationService:
    """Apply one user decision to multiple scene asset states."""

    def apply_to_remaining(
        self,
        states: list[SceneAssetState],
        start_scene_number: int,
        decision: AssetUserDecision,
    ) -> int:

        updated = 0

        for state in states:

            if state.scene_number < start_scene_number:
                continue

            state.user_decision = decision

            if decision == AssetUserDecision.SEARCH_STOCK:
                state.selected_source = SceneSourceType.STOCK_FOOTAGE
                state.status = AssetWorkflowStatus.SEARCHING_STOCK

            elif decision == AssetUserDecision.MANUAL_UPLOAD:
                state.selected_source = SceneSourceType.MANUAL_UPLOAD
                state.status = AssetWorkflowStatus.WAITING_FOR_MANUAL_UPLOAD

            elif decision == AssetUserDecision.IMAGE_TO_VIDEO:
                state.selected_source = SceneSourceType.IMAGE_TO_VIDEO
                state.status = AssetWorkflowStatus.IMAGE_TO_VIDEO_REQUIRED

            updated += 1

        return updated
