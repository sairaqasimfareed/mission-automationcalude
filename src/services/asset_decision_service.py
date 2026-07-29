from __future__ import annotations

from src.models.asset_state import (
    AssetUserDecision,
    AssetWorkflowStatus,
    SceneAssetState,
)
from src.models.media_strategy import SceneSourceType


class AssetDecisionService:
    """Applies the user's visual-source decision to a scene asset state."""

    def apply_decision(
        self,
        state: SceneAssetState,
        decision: AssetUserDecision,
        *,
        selected_candidate_index: int | None = None,
        manual_upload_path: str | None = None,
        image_prompt: str | None = None,
        apply_to_remaining_scenes: bool = False,
    ) -> SceneAssetState:
        state.user_decision = decision
        state.apply_decision_to_remaining_scenes = (
            apply_to_remaining_scenes
        )
        state.errors.clear()

        if decision == AssetUserDecision.USE_LOCAL:
            self._apply_local_decision(
                state=state,
                selected_candidate_index=selected_candidate_index,
            )

        elif decision == AssetUserDecision.SEARCH_STOCK:
            state.selected_source = SceneSourceType.STOCK_FOOTAGE
            state.selected_candidate = None
            state.status = AssetWorkflowStatus.SEARCHING_STOCK

        elif decision == AssetUserDecision.MANUAL_UPLOAD:
            state.selected_source = SceneSourceType.MANUAL_UPLOAD
            state.selected_candidate = None
            state.manual_upload_path = manual_upload_path
            state.status = (
                AssetWorkflowStatus.WAITING_FOR_MANUAL_UPLOAD
            )

        elif decision == AssetUserDecision.IMAGE_TO_VIDEO:
            state.selected_source = SceneSourceType.IMAGE_TO_VIDEO
            state.selected_candidate = None
            state.image_prompt = image_prompt
            state.status = (
                AssetWorkflowStatus.IMAGE_TO_VIDEO_REQUIRED
            )

        else:
            raise ValueError(
                f"Unsupported asset decision: {decision}"
            )

        return state

    @staticmethod
    def _apply_local_decision(
        state: SceneAssetState,
        selected_candidate_index: int | None,
    ) -> None:
        if not state.local_candidates:
            raise ValueError(
                "Local asset cannot be selected because "
                "no local candidates are available."
            )

        if selected_candidate_index is None:
            raise ValueError(
                "A local candidate index is required."
            )

        if not 0 <= selected_candidate_index < len(
            state.local_candidates
        ):
            raise IndexError(
                "Selected local candidate index is invalid."
            )

        candidate = state.local_candidates[
            selected_candidate_index
        ]

        state.selected_source = SceneSourceType.LOCAL_LIBRARY
        state.selected_candidate = candidate
        state.status = AssetWorkflowStatus.READY