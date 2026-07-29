from src.models.asset_index import (
    AssetIndex,
    IndexedAsset,
    IndexedAssetSource,
    IndexedAssetType,
)

index = AssetIndex()

video_asset = IndexedAsset(
    asset_type=IndexedAssetType.VIDEO,
    source=IndexedAssetSource.LOCAL_LIBRARY,
    file_path="assets/videos/local/ancient_tunnel.mp4",
    title="Ancient Underground Tunnel",
    provider="Local Library",
    license_type="owned",
    duration_seconds=8.0,
    resolution="3840x2160",
    aspect_ratio="16:9",
    tags=[
        "underground",
        "tunnel",
        "ancient",
    ],
    keywords=[
        "hidden city",
        "stone corridor",
    ],
)

music_asset = IndexedAsset(
    asset_type=IndexedAssetType.MUSIC,
    source=IndexedAssetSource.LOCAL_LIBRARY,
    file_path="assets/music/mystery/theme.mp3",
    title="Dark Mystery Theme",
    provider="Local Library",
    license_type="royalty_free",
    duration_seconds=120.0,
    tags=[
        "mystery",
        "dark",
        "cinematic",
    ],
)

index.add(video_asset)
index.add(music_asset)

video_results = index.search(
    asset_type=IndexedAssetType.VIDEO,
    query="tunnel",
)

music_results = index.search(
    asset_type=IndexedAssetType.MUSIC,
    query="mystery",
)

print("Total assets:", len(index.assets))
print("Video results:", len(video_results))
print("Music results:", len(music_results))
print("Video file:", video_results[0].file_path)
print("Music file:", music_results[0].file_path)

assert len(index.assets) == 2
assert len(video_results) == 1
assert len(music_results) == 1
assert video_results[0].title == "Ancient Underground Tunnel"
assert music_results[0].title == "Dark Mystery Theme"

print("Asset Index tests completed successfully.")
