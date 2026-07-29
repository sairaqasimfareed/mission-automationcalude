from src.models.asset_index import (
    AssetIndex,
    IndexedAsset,
    IndexedAssetSource,
    IndexedAssetType,
)
from src.models.scene import Scene, SceneStatus
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
            usage_count=2,
        ),
        IndexedAsset(
            asset_type=IndexedAssetType.VIDEO,
            source=IndexedAssetSource.LOCAL_LIBRARY,
            file_path="assets/videos/local/forest.mp4",
            title="Green Forest",
            provider="Local Library",
            license_type="owned",
            duration_seconds=10,
            resolution="1920x1080",
            tags=[
                "forest",
                "trees",
            ],
        ),
        IndexedAsset(
            asset_type=IndexedAssetType.MUSIC,
            source=IndexedAssetSource.LOCAL_LIBRARY,
            file_path="assets/music/mystery.mp3",
            title="Mystery Music",
            provider="Local Library",
            license_type="royalty_free",
            duration_seconds=120,
            tags=[
                "mystery",
                "dark",
            ],
        ),
    ]
)

scene = Scene(
    scene_number=1,
    title="Hidden Underground City",
    narration=("The camera enters an ancient stone tunnel beneath the city."),
    visual_prompt=("Cinematic ancient underground tunnel and stone corridor"),
    estimated_duration_seconds=8,
    status=SceneStatus.READY,
)

service = LocalAssetSearchService(asset_index)

results = service.search_for_scene(scene)

print("Results:", len(results))

for result in results:
    print("Title:", result.title)
    print("File:", result.file_path)
    print("Score:", result.score)

assert len(results) == 1
assert results[0].title == "Ancient Underground Tunnel"
assert results[0].file_path == ("assets/videos/local/ancient_tunnel.mp4")
assert results[0].score > 0

print("Local Asset Search Service tests completed successfully.")
