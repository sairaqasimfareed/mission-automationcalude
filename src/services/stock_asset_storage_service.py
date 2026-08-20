from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from pydantic import Field

from src.models.asset_index import (
    AssetIndex,
    IndexedAsset,
    IndexedAssetSource,
    IndexedAssetType,
)
from src.models.base import MissionBaseModel
from src.services.stock_download_service import (
    StockDownloadResult,
)


class StockAssetStorageResult(MissionBaseModel):
    """Result returned after storing or reusing a stock asset."""

    success: bool

    asset: IndexedAsset | None = None

    reused_existing: bool = False
    moved_new_file: bool = False

    message: str = ""

    warnings: list[str] = Field(
        default_factory=list,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )


class StockAssetStorageService:
    """
    Stores downloaded stock assets in permanent project storage.

    Responsibilities:

    - validate successful download results
    - reuse duplicate assets by SHA-256 hash
    - move temporary files into project storage
    - register stock assets in AssetIndex
    - preserve provider and licensing metadata
    """

    def __init__(
        self,
        *,
        storage_root: str | Path,
        asset_index: AssetIndex,
    ) -> None:
        self.storage_root = Path(storage_root).expanduser().resolve()

        self.asset_index = asset_index

        self.storage_root.mkdir(
            parents=True,
            exist_ok=True,
        )

    def store_downloaded_video(
        self,
        *,
        download_result: StockDownloadResult,
        project_id: str,
        scene_number: int,
        title: str,
        provider_name: str,
        license_type: str | None = None,
        provider_asset_id: str | None = None,
        source_url: str | None = None,
        duration_seconds: float = 0.0,
        resolution: str | None = None,
        aspect_ratio: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> StockAssetStorageResult:
        """Store or reuse one successfully downloaded stock video."""

        normalized_project_id = self._sanitize_identifier(project_id)

        if scene_number < 1:
            raise ValueError("Scene number must be at least 1.")

        normalized_title = title.strip()

        if not normalized_title:
            raise ValueError("Stock asset title cannot be empty.")

        normalized_provider_name = provider_name.strip()

        if not normalized_provider_name:
            raise ValueError("Stock provider name cannot be empty.")

        if not download_result.success:
            return StockAssetStorageResult(
                success=False,
                message=(
                    download_result.message or "Stock download was not successful."
                ),
                warnings=list(download_result.warnings),
                metadata=dict(download_result.metadata),
            )

        if not download_result.temporary_file_path:
            return StockAssetStorageResult(
                success=False,
                message=(
                    "Successful stock download result "
                    "does not contain a temporary file path."
                ),
            )

        if not download_result.content_hash:
            return StockAssetStorageResult(
                success=False,
                message=(
                    "Successful stock download result "
                    "does not contain a content hash."
                ),
            )

        temporary_file = (
            Path(download_result.temporary_file_path).expanduser().resolve()
        )

        if not temporary_file.exists():
            return StockAssetStorageResult(
                success=False,
                message=("Downloaded stock temporary file " "does not exist."),
                metadata={
                    "temporary_file_path": str(temporary_file),
                },
            )

        if not temporary_file.is_file():
            return StockAssetStorageResult(
                success=False,
                message=("Downloaded stock temporary path " "is not a file."),
                metadata={
                    "temporary_file_path": str(temporary_file),
                },
            )

        existing_asset = self._find_by_hash(download_result.content_hash)

        if existing_asset is not None:
            self._delete_temporary_file(temporary_file)

            return StockAssetStorageResult(
                success=True,
                asset=existing_asset,
                reused_existing=True,
                moved_new_file=False,
                message=("An identical stock asset already " "exists and was reused."),
                warnings=list(download_result.warnings),
                metadata={
                    "content_hash": (download_result.content_hash),
                },
            )

        project_directory = self.storage_root / normalized_project_id / "stock"

        project_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        safe_title = self._sanitize_filename(normalized_title)

        extension = temporary_file.suffix.lower() or ".mp4"

        destination_name = (
            f"scene_{scene_number:03}_"
            f"{download_result.content_hash[:12]}_"
            f"{safe_title}"
            f"{extension}"
        )

        destination = project_directory / destination_name

        try:
            shutil.move(
                str(temporary_file),
                str(destination),
            )
        except OSError as error:
            return StockAssetStorageResult(
                success=False,
                message=(
                    "Downloaded stock asset could not be " "moved into project storage."
                ),
                warnings=list(download_result.warnings),
                metadata={
                    "temporary_file_path": str(temporary_file),
                    "destination_path": str(destination),
                    "error_type": type(error).__name__,
                },
            )

        cleaned_tags = self._clean_tags(tags or [])

        asset_metadata: dict[str, Any] = {
            "project_id": normalized_project_id,
            "scene_number": scene_number,
            "provider_name": (normalized_provider_name),
            "extension": extension,
        }

        if provider_asset_id:
            asset_metadata["provider_asset_id"] = provider_asset_id.strip()

        if source_url:
            asset_metadata["source_url"] = source_url.strip()

        asset_metadata.update(download_result.metadata)

        asset_metadata.update(metadata or {})

        stored_asset = IndexedAsset(
            asset_type=IndexedAssetType.VIDEO,
            source=IndexedAssetSource.STOCK,
            file_path=str(destination.resolve()),
            title=normalized_title,
            provider=normalized_provider_name,
            license_type=license_type,
            duration_seconds=duration_seconds,
            resolution=resolution,
            aspect_ratio=aspect_ratio,
            file_size_bytes=(destination.stat().st_size),
            content_hash=(download_result.content_hash),
            tags=cleaned_tags,
            keywords=list(cleaned_tags),
            metadata=asset_metadata,
        )

        self.asset_index.add(stored_asset)

        return StockAssetStorageResult(
            success=True,
            asset=stored_asset,
            reused_existing=False,
            moved_new_file=True,
            message=("Downloaded stock asset was stored " "successfully."),
            warnings=list(download_result.warnings),
            metadata={
                "content_hash": (download_result.content_hash),
                "destination_path": str(destination.resolve()),
            },
        )

    def _find_by_hash(
        self,
        content_hash: str,
    ) -> IndexedAsset | None:
        """Return an indexed duplicate by content hash."""

        for asset in self.asset_index.assets:
            if asset.content_hash == content_hash:
                return asset

        return None

    @staticmethod
    def _delete_temporary_file(
        file_path: Path,
    ) -> None:
        """Delete an unused temporary download safely."""

        try:
            file_path.unlink(missing_ok=True)
        except OSError:
            pass

    @staticmethod
    def _sanitize_identifier(
        value: str,
    ) -> str:
        """Create a safe project directory identifier."""

        normalized = value.strip()

        if not normalized:
            raise ValueError("Project ID cannot be empty.")

        safe_value = "".join(
            character if (character.isalnum() or character in {"-", "_"}) else "_"
            for character in normalized
        )

        return safe_value.strip("_") or "project"

    @staticmethod
    def _sanitize_filename(
        value: str,
    ) -> str:
        """Create a safe filename stem."""

        safe_value = "".join(
            character if (character.isalnum() or character in {"-", "_"}) else "_"
            for character in value.strip()
        )

        return safe_value.strip("_") or "stock_asset"

    @staticmethod
    def _clean_tags(
        values: list[str],
    ) -> list[str]:
        """Normalize and deduplicate stock asset tags."""

        cleaned: list[str] = []

        for value in values:
            normalized = value.strip().lower()

            if normalized and normalized not in cleaned:
                cleaned.append(normalized)

        return cleaned
