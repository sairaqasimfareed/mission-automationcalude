from src.models.asset_state import (
    AssetCandidate,
    AssetUserDecision,
    AssetWorkflowStatus,
    SceneAssetState,
)
from src.models.media_strategy import SceneSourceType


candidate = AssetCandidate(
    title="Ancient Tunnel Clip",
    source_type=SceneSourceType.LOCAL_LIBRARY,
    file_path="assets/videos/local/ancient_tunnel.mp4",
    duration_seconds=8.0,
    resolution="3840x2160",
    aspect_ratio="16:9",
    last_used_at="2026-07-12",
    usage_count=3,
    score=0.92,
    tags=[
        "underground",
        "tunnel",
        "ancient",
    ],
)

state = SceneAssetState(
    scene_id="scene-001",
    scene_number=1,
    status=AssetWorkflowStatus.LOCAL_RESULTS_AVAILABLE,
    local_search_query="ancient underground tunnel",
    local_candidates=[candidate],
)

print("Scene:", state.scene_number)
print("Status:", state.status)
print("Local results:", len(state.local_candidates))
print("Candidate:", state.local_candidates[0].title)
print("Resolution:", state.local_candidates[0].resolution)
print("Usage count:", state.local_candidates[0].usage_count)

state.status = AssetWorkflowStatus.WAITING_FOR_USER_DECISION
state.user_decision = AssetUserDecision.USE_LOCAL
state.selected_source = SceneSourceType.LOCAL_LIBRARY
state.selected_candidate = candidate

print("Decision:", state.user_decision)
print("Selected source:", state.selected_source)
print("Selected file:", state.selected_candidate.file_path)

assert state.status == (
    AssetWorkflowStatus.WAITING_FOR_USER_DECISION
)
assert state.user_decision == AssetUserDecision.USE_LOCAL
assert state.selected_source == SceneSourceType.LOCAL_LIBRARY
assert state.selected_candidate is not None
assert state.selected_candidate.usage_count == 3

print("Asset State tests completed successfully.")