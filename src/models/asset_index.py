from __future__ import annotations

from enum import Enum

from pydantic import Field

from src.models.base import MissionBaseModel


class IndexedAssetType(str, Enum):
    VIDEO = "video"
    IMAGE = "image"
    MUSIC = "music"
    SOUND_EFFECT = "sound_effect"


class IndexedAssetSource(str, Enum):
    MANUAL_UPLOAD = "manual_upload"
    LOCAL_LIBRARY = "local_library"
    STOCK = "stock"
    GENERATED = "generated"


class IndexedAsset(MissionBaseModel):
    """Metadata record for one reusable media asset."""

    asset_type: IndexedAssetType
    source: IndexedAssetSource

    file_path: str

    title: str = ""
    provider: str | None = None
    license_type: str | None = None

    duration_seconds: float = 0.0
    resolution: str | None = None
    aspect_ratio: str | None = None

    file_size_bytes: int = 0
    content_hash: str | None = None

    tags: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)

    usage_count: int = 0
    last_used_at: str | None = None

    metadata: dict = Field(default_factory=dict)


class AssetIndex(MissionBaseModel):
    """In-memory index of reusable media assets."""

    assets: list[IndexedAsset] = Field(default_factory=list)

    def add(self, asset: IndexedAsset) -> None:
        self.assets.append(asset)

    def search(
        self,
        *,
        asset_type: IndexedAssetType | None = None,
        query: str | None = None,
    ) -> list[IndexedAsset]:
        results = self.assets

        if asset_type is not None:
            results = [asset for asset in results if asset.asset_type == asset_type]

        if query:
            normalized_query = query.lower()

            results = [
                asset
                for asset in results
                if normalized_query in asset.title.lower()
                or any(normalized_query in tag.lower() for tag in asset.tags)
                or any(
                    normalized_query in keyword.lower() for keyword in asset.keywords
                )
            ]

        return results
