from __future__ import annotations

from src.models.asset_state import (
    AssetUserDecision,
    AssetWorkflowStatus,
    SceneAssetState,
)
from src.models.media_strategy import SceneSourceType


class SceneDecisionPropagationService:
    """Apply one general asset decision to multiple scene states."""

    PROPAGATABLE_DECISIONS = {
        AssetUserDecision.REQUEST_MANUAL_UPLOAD,
        AssetUserDecision.MANUAL_UPLOAD,
        AssetUserDecision.SEARCH_STOCK,
        AssetUserDecision.SKIP_SCENE,
    }

    def apply_to_remaining(
        self,
        states: list[SceneAssetState],
        start_scene_number: int,
        decision: AssetUserDecision,
    ) -> int:
        """
        Apply a non-candidate-specific decision to remaining scenes.

        Local and stock candidate selections cannot be propagated
        because every scene may have different candidates.
        """

        if start_scene_number < 1:
            raise ValueError(
                "Start scene number must be at least 1."
            )

        if decision == AssetUserDecision.IMAGE_TO_VIDEO:
            raise ValueError(
                "Image-to-video is disabled in the active "
                "visual workflow."
            )

        if decision not in self.PROPAGATABLE_DECISIONS:
            raise ValueError(
                "This asset decision cannot be propagated "
                "without scene-specific information."
            )

        updated_count = 0

        for state in states:
            if state.scene_number < start_scene_number:
                continue

            if state.is_terminal:
                continue

            self._apply_general_decision(
                state=state,
                decision=decision,
            )

            state.apply_decision_to_remaining_scenes = True
            updated_count += 1

        return updated_count

    @staticmethod
    def _apply_general_decision(
        *,
        state: SceneAssetState,
        decision: AssetUserDecision,
    ) -> None:
        """Apply one supported general decision."""

        state.user_decision = decision
        state.clear_active_failure()
        state.selected_candidate = None

        if decision in {
            AssetUserDecision.REQUEST_MANUAL_UPLOAD,
            AssetUserDecision.MANUAL_UPLOAD,
        }:
            if state.manual_upload_module_enabled:
                state.selected_source = (
                    SceneSourceType.MANUAL_UPLOAD
                )
                state.manual_upload_requested = True
                state.manual_upload_declined = False
                state.status = (
                    AssetWorkflowStatus
                    .WAITING_FOR_MANUAL_UPLOAD
                )
            elif state.stock_module_enabled:
                state.selected_source = (
                    SceneSourceType.STOCK_FOOTAGE
                )
                state.status = (
                    AssetWorkflowStatus.SEARCHING_STOCK
                )
            else:
                state.selected_source = None
                state.status = (
                    AssetWorkflowStatus
                    .WAITING_FOR_RECOVERY_DECISION
                )

            return

        if decision == AssetUserDecision.SEARCH_STOCK:
            if state.stock_module_enabled:
                state.selected_source = (
                    SceneSourceType.STOCK_FOOTAGE
                )
                state.status = (
                    AssetWorkflowStatus.SEARCHING_STOCK
                )
            elif state.manual_upload_module_enabled:
                state.selected_source = (
                    SceneSourceType.MANUAL_UPLOAD
                )
                state.manual_upload_requested = True
                state.status = (
                    AssetWorkflowStatus
                    .WAITING_FOR_MANUAL_UPLOAD
                )
            else:
                state.selected_source = None
                state.status = (
                    AssetWorkflowStatus
                    .WAITING_FOR_RECOVERY_DECISION
                )

            return

        if decision == AssetUserDecision.SKIP_SCENE:
            state.selected_source = None
            state.skipped = True
            state.placeholder_requested = False
            state.status = AssetWorkflowStatus.SKIPPED
            return

        raise ValueError(
            f"Unsupported propagated decision: {decision}"
        )