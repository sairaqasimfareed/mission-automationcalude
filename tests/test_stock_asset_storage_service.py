from __future__ import annotations

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

from src.models.asset_index import (
    AssetIndex,
    IndexedAssetSource,
    IndexedAssetType,
)
from src.services.stock_asset_storage_service import (
    StockAssetStorageService,
)
from src.services.stock_download_service import (
    StockDownloadResult,
)

with TemporaryDirectory() as temporary_directory:
    root = Path(temporary_directory)

    temporary_download_directory = root / "downloads"

    permanent_storage_directory = root / "projects"

    temporary_download_directory.mkdir(
        parents=True,
    )

    downloaded_file = temporary_download_directory / "downloaded_stock.mp4"

    file_content = b"stock-video-content"

    downloaded_file.write_bytes(file_content)

    content_hash = hashlib.sha256(file_content).hexdigest()

    download_result = StockDownloadResult(
        success=True,
        source_url=("https://example.com/" "downloaded_stock.mp4"),
        temporary_file_path=str(downloaded_file),
        content_hash=content_hash,
        file_size_bytes=len(file_content),
        content_type="video/mp4",
        message=("Stock asset downloaded successfully."),
        metadata={
            "provider_name": "Pexels",
            "provider_asset_id": "stock-001",
        },
    )

    asset_index = AssetIndex()

    storage_service = StockAssetStorageService(
        storage_root=(permanent_storage_directory),
        asset_index=asset_index,
    )

    first_result = storage_service.store_downloaded_video(
        download_result=download_result,
        project_id="history-project",
        scene_number=1,
        title="Roman Soldiers Marching",
        provider_name="Pexels",
        license_type="royalty_free",
        provider_asset_id="stock-001",
        source_url=download_result.source_url,
        duration_seconds=8,
        resolution="1920x1080",
        aspect_ratio="16:9",
        tags=[
            "Roman",
            "Soldiers",
            "roman",
        ],
    )

    print(
        "Stored stock:",
        first_result.success,
    )

    print(
        "Reused stock:",
        first_result.reused_existing,
    )

    assert first_result.success is True
    assert first_result.asset is not None
    assert first_result.moved_new_file is True
    assert first_result.reused_existing is False

    stored_asset = first_result.asset

    assert stored_asset.asset_type == IndexedAssetType.VIDEO

    assert stored_asset.source == IndexedAssetSource.STOCK

    assert stored_asset.provider == "Pexels"
    assert stored_asset.license_type == "royalty_free"

    assert stored_asset.content_hash == content_hash

    assert stored_asset.tags == [
        "roman",
        "soldiers",
    ]

    stored_path = Path(stored_asset.file_path).resolve()

    resolved_storage_directory = permanent_storage_directory.resolve()

    assert stored_path.exists()

    assert resolved_storage_directory in stored_path.parents

    assert stored_path.read_bytes() == file_content

    assert downloaded_file.exists() is False
    assert len(asset_index.assets) == 1

    duplicate_temporary_file = temporary_download_directory / "duplicate_stock.mp4"

    duplicate_temporary_file.write_bytes(file_content)

    duplicate_download_result = StockDownloadResult(
        success=True,
        source_url=("https://example.com/" "duplicate_stock.mp4"),
        temporary_file_path=str(duplicate_temporary_file),
        content_hash=content_hash,
        file_size_bytes=len(file_content),
        content_type="video/mp4",
        message=("Stock asset downloaded successfully."),
    )

    duplicate_result = storage_service.store_downloaded_video(
        download_result=(duplicate_download_result),
        project_id="history-project",
        scene_number=2,
        title="Roman Soldiers Duplicate",
        provider_name="Pexels",
    )

    assert duplicate_result.success is True
    assert duplicate_result.reused_existing is True
    assert duplicate_result.moved_new_file is False
    assert duplicate_result.asset is not None
    assert duplicate_result.asset.id == stored_asset.id

    assert duplicate_temporary_file.exists() is False

    assert len(asset_index.assets) == 1


with TemporaryDirectory() as temporary_directory:
    root = Path(temporary_directory)

    failed_service = StockAssetStorageService(
        storage_root=root / "storage",
        asset_index=AssetIndex(),
    )

    failed_download_result = StockDownloadResult(
        success=False,
        source_url=("https://example.com/" "failed.mp4"),
        message=("Stock download failed."),
        error_type="ConnectionError",
        retryable=True,
    )

    failed_storage_result = failed_service.store_downloaded_video(
        download_result=(failed_download_result),
        project_id="failed-project",
        scene_number=1,
        title="Failed Stock",
        provider_name="Pexels",
    )

    assert failed_storage_result.success is False

    assert failed_storage_result.asset is None


print("Stock Asset Storage Service tests " "completed successfully.")
