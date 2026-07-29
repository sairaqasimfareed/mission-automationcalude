from src.models.asset_index import (
    AssetIndex,
    IndexedAsset,
    IndexedAssetSource,
    IndexedAssetType,
)
from src.models.asset_state import AssetWorkflowStatus
from src.models.scene import Scene, SceneStatus
from src.services.asset_manager import AssetManager
from src.services.local_asset_search_service import (
    LocalAssetSearchService,
)

asset_index = AssetIndex(
    assets=[
        IndexedAsset(
            asset_type=IndexedAssetType.VIDEO,
            source=IndexedAssetSource.LOCAL_LIBRARY,
            file_path="assets/videos/local/ancient_tunnel.mp4",
            title="Ancient Underground Tunnel",
            provider="Local Library",
            license_type="owned",
            duration_seconds=8,
            resolution="3840x2160",
            aspect_ratio="16:9",
            tags=[
                "ancient",
                "underground",
                "tunnel",
            ],
            keywords=[
                "hidden city",
                "stone corridor",
            ],
        ),
    ]
)

search_service = LocalAssetSearchService(asset_index)
manager = AssetManager(search_service)


matching_scene = Scene(
    scene_number=1,
    title="Hidden Underground City",
    narration="The camera enters an ancient tunnel.",
    visual_prompt="Ancient underground tunnel",
    estimated_duration_seconds=8,
    status=SceneStatus.READY,
)

matching_state = manager.search_local_assets(matching_scene)

print("Matching status:", matching_state.status)
print(
    "Matching results:",
    len(matching_state.local_candidates),
)

assert matching_state.status == AssetWorkflowStatus.LOCAL_RESULTS_AVAILABLE
assert len(matching_state.local_candidates) == 1


missing_scene = Scene(
    scene_number=2,
    title="Ocean City",
    narration="The camera moves beneath the ocean.",
    visual_prompt="Deep underwater futuristic city",
    estimated_duration_seconds=8,
    status=SceneStatus.READY,
)

missing_state = manager.search_local_assets(missing_scene)

print("Missing status:", missing_state.status)
print(
    "Missing results:",
    len(missing_state.local_candidates),
)
print("Warnings:", missing_state.warnings)

assert missing_state.status == AssetWorkflowStatus.WAITING_FOR_USER_DECISION
assert len(missing_state.local_candidates) == 0
assert len(missing_state.warnings) == 1

print("Asset Manager tests completed successfully.")
