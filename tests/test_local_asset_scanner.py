from pathlib import Path

from src.models.asset_index import IndexedAssetType
from src.services.local_asset_scanner import LocalAssetScanner

test_root = Path("assets/test_scanner")

video_dir = test_root / "videos"
music_dir = test_root / "music"
sfx_dir = test_root / "sfx"
image_dir = test_root / "images"

video_dir.mkdir(parents=True, exist_ok=True)
music_dir.mkdir(parents=True, exist_ok=True)
sfx_dir.mkdir(parents=True, exist_ok=True)
image_dir.mkdir(parents=True, exist_ok=True)

(video_dir / "ancient_tunnel.mp4").write_text(
    "dummy video",
    encoding="utf-8",
)

(music_dir / "mystery_theme.mp3").write_text(
    "dummy music",
    encoding="utf-8",
)

(sfx_dir / "door_impact.wav").write_text(
    "dummy sfx",
    encoding="utf-8",
)

(image_dir / "ancient_map.png").write_text(
    "dummy image",
    encoding="utf-8",
)

scanner = LocalAssetScanner()
index = scanner.scan(test_root)

print("Total assets:", len(index.assets))

video_assets = index.search(
    asset_type=IndexedAssetType.VIDEO,
)

music_assets = index.search(
    asset_type=IndexedAssetType.MUSIC,
)

sfx_assets = index.search(
    asset_type=IndexedAssetType.SOUND_EFFECT,
)

image_assets = index.search(
    asset_type=IndexedAssetType.IMAGE,
)

print("Videos:", len(video_assets))
print("Music:", len(music_assets))
print("Sound effects:", len(sfx_assets))
print("Images:", len(image_assets))

assert len(index.assets) == 4
assert len(video_assets) == 1
assert len(music_assets) == 1
assert len(sfx_assets) == 1
assert len(image_assets) == 1

assert video_assets[0].content_hash is not None
assert music_assets[0].provider == "Local Library"

print("Local Asset Scanner tests completed successfully.")
