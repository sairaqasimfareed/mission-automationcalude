from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from src.models.asset_index import (
    AssetIndex,
    IndexedAssetSource,
    IndexedAssetType,
)
from src.services.asset_storage_service import (
    AssetStorageService,
)


with TemporaryDirectory() as temporary_directory:
    root = Path(temporary_directory)

    source_directory = root / "incoming"
    storage_directory = root / "projects"

    source_directory.mkdir(
        parents=True,
    )

    source_file = (
        source_directory
        / "roman_army_clip.mp4"
    )

    source_file.write_bytes(
        b"test-video-content"
    )

    asset_index = AssetIndex()

    service = AssetStorageService(
        storage_root=storage_directory,
        asset_index=asset_index,
    )

    first_result = service.store_manual_upload(
        source_path=source_file,
        project_id="history-project",
        scene_number=1,
        asset_type=IndexedAssetType.VIDEO,
        tags=[
            "Roman",
            "Army",
            "roman",
        ],
    )

    print("Stored:", first_result.success)
    print("Reused:", first_result.reused_existing)

    assert first_result.success is True
    assert first_result.asset is not None
    assert first_result.copied_new_file is True
    assert first_result.reused_existing is False

    stored_asset = first_result.asset

    assert (
        stored_asset.source
        == IndexedAssetSource.MANUAL_UPLOAD
    )

    assert (
        stored_asset.asset_type
        == IndexedAssetType.VIDEO
    )

    assert stored_asset.content_hash is not None
    assert stored_asset.provider == "Manual Upload"
    assert stored_asset.license_type == "user_provided"

    assert stored_asset.tags == [
        "roman",
        "army",
    ]

    stored_path = Path(
        stored_asset.file_path
    ).resolve()

    resolved_storage_directory = (
        storage_directory.resolve()
    )

    assert stored_path.exists()

    assert (
        resolved_storage_directory
        in stored_path.parents
    )

    assert len(asset_index.assets) == 1

    duplicate_result = (
        service.store_manual_upload(
            source_path=source_file,
            project_id="history-project",
            scene_number=2,
        )
    )

    assert duplicate_result.success is True
    assert duplicate_result.reused_existing is True
    assert duplicate_result.copied_new_file is False

    assert len(asset_index.assets) == 1


print(
    "Asset Storage Service tests "
    "completed successfully."
)