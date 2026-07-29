from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AssetType(str, Enum):
    VIDEO = "video"
    IMAGE = "image"
    MUSIC = "music"
    SOUND_EFFECT = "sound_effect"


@dataclass(slots=True)
class AssetSearchResult:
    """
    Generic asset returned from any asset provider.
    """

    asset_type: AssetType
    provider: str

    title: str

    file_url: str

    thumbnail_url: str | None = None

    license_type: str = "unknown"

    duration_seconds: int = 0

    resolution: str | None = None


class AssetSearchService:
    """
    Universal Asset Search Service.

    Future providers:

    - Local Library
    - Pexels
    - Pixabay
    - Storyblocks
    - Envato
    - Music Libraries
    - Sound Effect Libraries
    """

    def search(
        self,
        asset_type: AssetType,
        query: str,
    ) -> list[AssetSearchResult]:

        return [
            AssetSearchResult(
                asset_type=asset_type,
                provider="Dry Run",
                title=query,
                file_url="https://example.com/demo.file",
                thumbnail_url=None,
                license_type="royalty_free",
                duration_seconds=8,
                resolution="1920x1080",
            )
        ]
