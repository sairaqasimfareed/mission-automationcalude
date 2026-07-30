from src.models.asset_state import (
    AssetUserDecision,
    AssetWorkflowStatus,
    SceneAssetState,
)
from src.models.media_strategy import SceneSourceType
from src.services.scene_decision_propagation_service import (
    SceneDecisionPropagationService,
)


states = [
    SceneAssetState(
        scene_id=f"scene-{scene_number}",
        scene_number=scene_number,
        status=(
            AssetWorkflowStatus
            .WAITING_FOR_USER_DECISION
        ),
    )
    for scene_number in range(1, 6)
]


service = SceneDecisionPropagationService()


updated = service.apply_to_remaining(
    states=states,
    start_scene_number=3,
    decision=(
        AssetUserDecision.REQUEST_MANUAL_UPLOAD
    ),
)

print("Manual upload states updated:", updated)

assert updated == 3

for state in states:
    if state.scene_number < 3:
        assert (
            state.status
            == AssetWorkflowStatus
            .WAITING_FOR_USER_DECISION
        )
        continue

    assert (
        state.selected_source
        == SceneSourceType.MANUAL_UPLOAD
    )

    assert (
        state.status
        == AssetWorkflowStatus
        .WAITING_FOR_MANUAL_UPLOAD
    )

    assert state.manual_upload_requested is True
    assert (
        state.apply_decision_to_remaining_scenes
        is True
    )


stock_states = [
    SceneAssetState(
        scene_id=f"stock-scene-{scene_number}",
        scene_number=scene_number,
        status=(
            AssetWorkflowStatus
            .WAITING_FOR_USER_DECISION
        ),
    )
    for scene_number in range(1, 4)
]

stock_updated = service.apply_to_remaining(
    states=stock_states,
    start_scene_number=1,
    decision=AssetUserDecision.SEARCH_STOCK,
)

assert stock_updated == 3

for state in stock_states:
    assert (
        state.status
        == AssetWorkflowStatus.SEARCHING_STOCK
    )

    assert (
        state.selected_source
        == SceneSourceType.STOCK_FOOTAGE
    )


skip_states = [
    SceneAssetState(
        scene_id=f"skip-scene-{scene_number}",
        scene_number=scene_number,
        status=(
            AssetWorkflowStatus
            .WAITING_FOR_USER_DECISION
        ),
    )
    for scene_number in range(1, 4)
]

skip_states[0].status = AssetWorkflowStatus.READY

skip_updated = service.apply_to_remaining(
    states=skip_states,
    start_scene_number=1,
    decision=AssetUserDecision.SKIP_SCENE,
)

assert skip_updated == 2
assert skip_states[0].status == AssetWorkflowStatus.READY

for state in skip_states[1:]:
    assert state.status == AssetWorkflowStatus.SKIPPED
    assert state.skipped is True


try:
    service.apply_to_remaining(
        states=states,
        start_scene_number=1,
        decision=AssetUserDecision.USE_LOCAL,
    )
except ValueError:
    print(
        "Candidate-specific propagation successfully blocked."
    )
else:
    raise AssertionError(
        "Local candidate selection should not propagate."
    )


try:
    service.apply_to_remaining(
        states=states,
        start_scene_number=1,
        decision=AssetUserDecision.IMAGE_TO_VIDEO,
    )
except ValueError:
    print(
        "Image-to-video propagation successfully blocked."
    )
else:
    raise AssertionError(
        "Image-to-video propagation should fail."
    )


print(
    "Scene Decision Propagation tests "
    "completed successfully."
)