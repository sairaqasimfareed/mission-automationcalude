from __future__ import annotations

import hashlib
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


class AssetStorageResult(MissionBaseModel):
    """Result returned after storing or reusing an asset."""

    success: bool

    asset: IndexedAsset | None = None

    reused_existing: bool = False
    copied_new_file: bool = False

    message: str = ""

    warnings: list[str] = Field(
        default_factory=list,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )


class AssetStorageService:
    """
    Stores validated project assets safely.

    Responsibilities:

    - project-specific storage
    - safe filenames
    - SHA-256 hashing
    - duplicate reuse
    - AssetIndex registration
    """

    def __init__(
        self,
        *,
        storage_root: str | Path,
        asset_index: AssetIndex,
    ) -> None:
        self.storage_root = (
            Path(storage_root)
            .expanduser()
            .resolve()
        )

        self.asset_index = asset_index

        self.storage_root.mkdir(
            parents=True,
            exist_ok=True,
        )

    def store_manual_upload(
        self,
        *,
        source_path: str | Path,
        project_id: str,
        scene_number: int,
        asset_type: IndexedAssetType = (
            IndexedAssetType.VIDEO
        ),
        title: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AssetStorageResult:
        """Store or reuse one validated manual upload."""

        normalized_project_id = (
            self._sanitize_identifier(project_id)
        )

        if scene_number < 1:
            raise ValueError(
                "Scene number must be at least 1."
            )

        source = (
            Path(source_path)
            .expanduser()
            .resolve()
        )

        if not source.exists():
            return AssetStorageResult(
                success=False,
                message=(
                    "Manual upload source file "
                    "does not exist."
                ),
                metadata={
                    "source_path": str(source),
                },
            )

        if not source.is_file():
            return AssetStorageResult(
                success=False,
                message=(
                    "Manual upload source path "
                    "is not a file."
                ),
                metadata={
                    "source_path": str(source),
                },
            )

        try:
            content_hash = self._calculate_hash(
                source
            )
        except OSError as error:
            return AssetStorageResult(
                success=False,
                message=(
                    "Manual upload hash could not "
                    "be calculated."
                ),
                metadata={
                    "source_path": str(source),
                    "error_type": type(error).__name__,
                },
            )

        existing_asset = self._find_by_hash(
            content_hash
        )

        if existing_asset is not None:
            return AssetStorageResult(
                success=True,
                asset=existing_asset,
                reused_existing=True,
                copied_new_file=False,
                message=(
                    "An identical asset already exists "
                    "and was reused."
                ),
                metadata={
                    "content_hash": content_hash,
                },
            )

        project_directory = (
            self.storage_root
            / normalized_project_id
            / "manual_uploads"
        )

        project_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        safe_stem = self._sanitize_filename(
            source.stem
        )

        destination_name = (
            f"scene_{scene_number:03}_"
            f"{content_hash[:12]}_"
            f"{safe_stem}"
            f"{source.suffix.lower()}"
        )

        destination = (
            project_directory
            / destination_name
        )

        try:
            shutil.copy2(
                source,
                destination,
            )
        except OSError as error:
            return AssetStorageResult(
                success=False,
                message=(
                    "Manual upload could not be copied "
                    "to project storage."
                ),
                metadata={
                    "source_path": str(source),
                    "destination_path": str(
                        destination
                    ),
                    "error_type": type(error).__name__,
                },
            )

        file_size_bytes = (
            destination.stat().st_size
        )

        cleaned_title = (
            title.strip()
            if title is not None
            and title.strip()
            else self._build_title(source)
        )

        cleaned_tags = self._clean_tags(
            tags or []
        )

        asset_metadata: dict[str, Any] = {
            "original_file_name": source.name,
            "original_source_path": str(source),
            "project_id": normalized_project_id,
            "scene_number": scene_number,
            "extension": source.suffix.lower(),
        }

        asset_metadata.update(
            metadata or {}
        )

        asset = IndexedAsset(
            asset_type=asset_type,
            source=IndexedAssetSource.MANUAL_UPLOAD,
            file_path=str(
                destination.resolve()
            ),
            title=cleaned_title,
            provider="Manual Upload",
            license_type="user_provided",
            file_size_bytes=file_size_bytes,
            content_hash=content_hash,
            tags=cleaned_tags,
            keywords=list(cleaned_tags),
            metadata=asset_metadata,
        )

        self.asset_index.add(asset)

        return AssetStorageResult(
            success=True,
            asset=asset,
            reused_existing=False,
            copied_new_file=True,
            message=(
                "Manual upload was stored successfully."
            ),
            metadata={
                "content_hash": content_hash,
                "destination_path": str(
                    destination.resolve()
                ),
            },
        )

    def _find_by_hash(
        self,
        content_hash: str,
    ) -> IndexedAsset | None:
        """Find an indexed duplicate by content hash."""

        for asset in self.asset_index.assets:
            if asset.content_hash == content_hash:
                return asset

        return None

    @staticmethod
    def _calculate_hash(
        file_path: Path,
    ) -> str:
        """Calculate the SHA-256 hash of one file."""

        hasher = hashlib.sha256()

        with file_path.open("rb") as file:
            while True:
                chunk = file.read(1024 * 1024)

                if not chunk:
                    break

                hasher.update(chunk)

        return hasher.hexdigest()

    @staticmethod
    def _sanitize_identifier(
        value: str,
    ) -> str:
        """Create a safe directory identifier."""

        normalized = value.strip()

        if not normalized:
            raise ValueError(
                "Project ID cannot be empty."
            )

        safe_value = "".join(
            character
            if character.isalnum()
            or character in {"-", "_"}
            else "_"
            for character in normalized
        )

        return safe_value.strip("_") or "project"

    @staticmethod
    def _sanitize_filename(
        value: str,
    ) -> str:
        """Create a safe filename stem."""

        safe_value = "".join(
            character
            if character.isalnum()
            or character in {"-", "_"}
            else "_"
            for character in value.strip()
        )

        return safe_value.strip("_") or "asset"

    @staticmethod
    def _build_title(
        file_path: Path,
    ) -> str:
        """Build a readable title from the filename."""

        return (
            file_path.stem
            .replace("_", " ")
            .replace("-", " ")
            .strip()
        )

    @staticmethod
    def _clean_tags(
        values: list[str],
    ) -> list[str]:
        """Normalize and deduplicate asset tags."""

        cleaned: list[str] = []

        for value in values:
            normalized = value.strip().lower()

            if (
                normalized
                and normalized not in cleaned
            ):
                cleaned.append(normalized)

        return cleaned