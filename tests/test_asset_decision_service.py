from src.models.asset_state import (
    AssetCandidate,
    AssetUserDecision,
    AssetWorkflowStatus,
    SceneAssetState,
)
from src.models.media_strategy import SceneSourceType
from src.services.asset_decision_service import (
    AssetDecisionService,
)


candidate = AssetCandidate(
    title="Ancient Tunnel",
    source_type=SceneSourceType.LOCAL_LIBRARY,
    file_path="assets/videos/local/tunnel.mp4",
    duration_seconds=8,
    resolution="1920x1080",
)

service = AssetDecisionService()


local_state = SceneAssetState(
    scene_id="scene-001",
    scene_number=1,
    status=AssetWorkflowStatus.LOCAL_RESULTS_AVAILABLE,
    local_candidates=[candidate],
)

local_result = service.apply_decision(
    state=local_state,
    decision=AssetUserDecision.USE_LOCAL,
    selected_candidate_index=0,
)

print("Local decision:", local_result.user_decision)
print("Local source:", local_result.selected_source)
print("Local status:", local_result.status)
print(
    "Selected file:",
    local_result.selected_candidate.file_path,
)

assert local_result.status == AssetWorkflowStatus.READY
assert (
    local_result.selected_source
    == SceneSourceType.LOCAL_LIBRARY
)
assert local_result.selected_candidate is not None


stock_state = SceneAssetState(
    scene_id="scene-002",
    scene_number=2,
    status=AssetWorkflowStatus.WAITING_FOR_USER_DECISION,
)

stock_result = service.apply_decision(
    state=stock_state,
    decision=AssetUserDecision.SEARCH_STOCK,
)

print("Stock decision:", stock_result.user_decision)
print("Stock status:", stock_result.status)

assert (
    stock_result.status
    == AssetWorkflowStatus.SEARCHING_STOCK
)
assert (
    stock_result.selected_source
    == SceneSourceType.STOCK_FOOTAGE
)


manual_state = SceneAssetState(
    scene_id="scene-003",
    scene_number=3,
    status=AssetWorkflowStatus.WAITING_FOR_USER_DECISION,
)

manual_result = service.apply_decision(
    state=manual_state,
    decision=AssetUserDecision.MANUAL_UPLOAD,
    apply_to_remaining_scenes=True,
)

print("Manual decision:", manual_result.user_decision)
print("Manual status:", manual_result.status)
print(
    "Apply to remaining:",
    manual_result.apply_decision_to_remaining_scenes,
)

assert (
    manual_result.status
    == AssetWorkflowStatus.WAITING_FOR_MANUAL_UPLOAD
)
assert (
    manual_result.selected_source
    == SceneSourceType.MANUAL_UPLOAD
)
assert manual_result.apply_decision_to_remaining_scenes is True


image_state = SceneAssetState(
    scene_id="scene-004",
    scene_number=4,
    status=AssetWorkflowStatus.WAITING_FOR_USER_DECISION,
)

image_result = service.apply_decision(
    state=image_state,
    decision=AssetUserDecision.IMAGE_TO_VIDEO,
    image_prompt="Ancient map with cinematic camera movement",
)

print("Image decision:", image_result.user_decision)
print("Image status:", image_result.status)
print("Image prompt:", image_result.image_prompt)

assert (
    image_result.status
    == AssetWorkflowStatus.IMAGE_TO_VIDEO_REQUIRED
)
assert (
    image_result.selected_source
    == SceneSourceType.IMAGE_TO_VIDEO
)

print("Asset Decision Service tests completed successfully.")