from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from src.models.asset_index import (
    IndexedAssetSource,
    IndexedAssetType,
)
from src.services.local_asset_library import (
    LocalAssetLibrary,
)

with TemporaryDirectory() as temporary_directory:
    root = Path(temporary_directory)

    history_directory = root / "videos" / "history"
    image_directory = root / "images"
    music_directory = root / "music"
    unsupported_directory = root / "documents"

    history_directory.mkdir(
        parents=True,
    )

    image_directory.mkdir(
        parents=True,
    )

    music_directory.mkdir(
        parents=True,
    )

    unsupported_directory.mkdir(
        parents=True,
    )

    roman_video = history_directory / "ancient_roman_soldiers_marching.mp4"

    egypt_video = history_directory / "ancient_egypt_pyramids.mov"

    roman_image = image_directory / "roman_colosseum.jpg"

    music_file = music_directory / "cinematic_history_theme.mp3"

    sound_effect_file = music_directory / "sword_clash.sfx.wav"

    unsupported_file = unsupported_directory / "research_notes.txt"

    roman_video.write_bytes(b"roman-video")
    egypt_video.write_bytes(b"egypt-video")
    roman_image.write_bytes(b"roman-image")
    music_file.write_bytes(b"music")
    sound_effect_file.write_bytes(b"sfx")
    unsupported_file.write_text(
        "Unsupported file.",
        encoding="utf-8",
    )

    library = LocalAssetLibrary(
        directories=[
            root,
        ]
    )

    index = library.refresh()

    print("Indexed assets:", len(index.assets))

    assert len(index.assets) == 5

    assert all(
        asset.source == IndexedAssetSource.LOCAL_LIBRARY for asset in index.assets
    )

    video_results = library.search(
        asset_type=IndexedAssetType.VIDEO,
    )

    assert len(video_results) == 2

    roman_results = library.search(
        query="roman soldiers",
        asset_type=IndexedAssetType.VIDEO,
    )

    print(
        "Roman result:",
        roman_results[0].title,
    )

    assert len(roman_results) >= 1
    assert roman_results[0].file_path == str(roman_video.resolve())

    limited_results = library.search(
        asset_type=IndexedAssetType.VIDEO,
        limit=1,
    )

    assert len(limited_results) == 1

    indexed_roman_video = library.find_by_path(roman_video)

    assert indexed_roman_video is not None
    assert indexed_roman_video.asset_type == IndexedAssetType.VIDEO

    assert indexed_roman_video.title == ("ancient roman soldiers marching")

    assert indexed_roman_video.file_size_bytes == (len(b"roman-video"))

    assert "roman" in indexed_roman_video.tags
    assert "history" in indexed_roman_video.tags

    statistics = library.statistics()

    print("Videos:", statistics.videos)
    print("Images:", statistics.images)
    print("Music:", statistics.music)
    print(
        "Sound effects:",
        statistics.sound_effects,
    )

    assert statistics.registered_directories == 1
    assert statistics.indexed_assets == 5
    assert statistics.videos == 2
    assert statistics.images == 1
    assert statistics.music == 1
    assert statistics.sound_effects == 1
    assert statistics.total_file_size_bytes > 0

    unregistered = library.unregister_directory(root)

    assert unregistered is True
    assert library.registered_directories == []

    duplicate_unregister = library.unregister_directory(root)

    assert duplicate_unregister is False

    library.register_directory(root)
    library.register_directory(root)

    assert len(library.registered_directories) == 1

    try:
        library.search(
            query="roman",
            limit=0,
        )
    except ValueError:
        print("Invalid local search limit " "successfully blocked.")
    else:
        raise AssertionError("Invalid local search limit should fail.")


with TemporaryDirectory() as temporary_directory:
    missing_directory = Path(temporary_directory) / "missing"

    empty_library = LocalAssetLibrary()

    try:
        empty_library.register_directory(missing_directory)
    except FileNotFoundError:
        print("Missing local directory " "successfully blocked.")
    else:
        raise AssertionError("Missing directory should fail.")


print("Local Asset Library tests " "completed successfully.")
