from __future__ import annotations

import hashlib
from pathlib import Path

from src.models.asset_index import (
    AssetIndex,
    IndexedAsset,
)
from src.services.local_asset_library import (
    LocalAssetLibrary,
)


class LocalAssetScanner:
    """
    Backward-compatible scanner built on LocalAssetLibrary.

    LocalAssetLibrary owns folder scanning and indexing.
    This facade adds file hashes and legacy metadata.
    """

    def scan(
        self,
        root_folder: str | Path = "assets",
    ) -> AssetIndex:
        """Scan one local folder and return an enriched asset index."""

        root_path = Path(root_folder).expanduser()

        if not root_path.exists():
            return AssetIndex()

        if not root_path.is_dir():
            raise NotADirectoryError(
                "Local asset scan path is not a directory: " f"{root_path}"
            )

        library = LocalAssetLibrary(
            directories=[
                root_path,
            ]
        )

        base_index = library.refresh()
        enriched_index = AssetIndex()

        for asset in base_index.assets:
            enriched_index.add(self._enrich_asset(asset))

        return enriched_index

    def _enrich_asset(
        self,
        asset: IndexedAsset,
    ) -> IndexedAsset:
        """Add file hash and local ownership metadata."""

        file_path = Path(asset.file_path)

        content_hash = self._calculate_hash(file_path) if file_path.exists() else None

        metadata = dict(asset.metadata)

        metadata.update(
            {
                "parent_folder": file_path.parent.name,
                "scanner": "LocalAssetScanner",
            }
        )

        return asset.model_copy(
            update={
                "provider": "Local Library",
                "license_type": "owned",
                "content_hash": content_hash,
                "metadata": metadata,
            }
        )

    @staticmethod
    def _calculate_hash(
        file_path: Path,
    ) -> str:
        """Calculate a SHA-256 hash without loading the full file."""

        hasher = hashlib.sha256()

        with file_path.open("rb") as file:
            while True:
                chunk = file.read(8192)

                if not chunk:
                    break

                hasher.update(chunk)

        return hasher.hexdigest()
