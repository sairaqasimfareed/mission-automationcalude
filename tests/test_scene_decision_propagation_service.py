from src.models.asset_state import (
    AssetUserDecision,
    AssetWorkflowStatus,
    SceneAssetState,
)
from src.models.media_strategy import SceneSourceType
from src.services.scene_decision_propagation_service import (
    SceneDecisionPropagationService,
)


states = []

for scene_number in range(1, 6):

    states.append(
        SceneAssetState(
            scene_id=f"scene-{scene_number}",
            scene_number=scene_number,
            status=AssetWorkflowStatus.WAITING_FOR_USER_DECISION,
        )
    )


service = SceneDecisionPropagationService()

updated = service.apply_to_remaining(
    states=states,
    start_scene_number=3,
    decision=AssetUserDecision.MANUAL_UPLOAD,
)

print("Updated:", updated)

assert updated == 3

for state in states:

    if state.scene_number >= 3:

        assert (
            state.selected_source
            == SceneSourceType.MANUAL_UPLOAD
        )

        assert (
            state.status
            == AssetWorkflowStatus.WAITING_FOR_MANUAL_UPLOAD
        )

print(
    "Scene Decision Propagation tests completed successfully."
)