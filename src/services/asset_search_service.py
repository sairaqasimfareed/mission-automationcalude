from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.services.stock_search_service import (
    StockSearchRequest,
    StockSearchService,
)


class AssetType(str, Enum):
    """Supported searchable media categories."""

    VIDEO = "video"
    IMAGE = "image"
    MUSIC = "music"
    SOUND_EFFECT = "sound_effect"


@dataclass(slots=True)
class AssetSearchResult:
    """Generic asset returned from any asset provider."""

    asset_type: AssetType
    provider: str
    title: str
    file_url: str

    provider_asset_id: str | None = None
    page_url: str | None = None
    thumbnail_url: str | None = None

    license_type: str = "unknown"
    attribution_required: bool = False
    attribution_text: str | None = None

    duration_seconds: float = 0.0
    resolution: str | None = None
    aspect_ratio: str | None = None

    width: int | None = None
    height: int | None = None

    quality: str | None = None
    score: float = 0.0

    metadata: dict[str, str] | None = None


class AssetSearchService:
    """
    Universal asset-search facade.

    Stock video searches are delegated to StockSearchService.
    Other asset categories remain ready for future adapters.
    """

    def __init__(
        self,
        stock_search_service: StockSearchService | None = None,
    ) -> None:
        self.stock_search_service = (
            stock_search_service
            or StockSearchService()
        )

    def search(
        self,
        asset_type: AssetType,
        query: str,
        *,
        limit: int = 15,
    ) -> list[AssetSearchResult]:
        """Search the requested asset category."""

        normalized_query = query.strip()

        if not normalized_query:
            raise ValueError(
                "Asset search query cannot be empty."
            )

        if limit < 1:
            raise ValueError(
                "Asset search limit must be at least 1."
            )

        if asset_type == AssetType.VIDEO:
            return self._search_stock_videos(
                query=normalized_query,
                limit=limit,
            )

        return []

    def _search_stock_videos(
        self,
        *,
        query: str,
        limit: int,
    ) -> list[AssetSearchResult]:
        """Search normalized stock-video providers."""

        stock_results = self.stock_search_service.search(
            StockSearchRequest(
                query=query,
                per_page=min(limit, 100),
            )
        )

        return [
            AssetSearchResult(
                asset_type=AssetType.VIDEO,
                provider=result.provider,
                provider_asset_id=(
                    result.provider_asset_id
                ),
                title=result.title,
                page_url=result.page_url,
                file_url=result.file_url,
                thumbnail_url=result.thumbnail_url,
                license_type=result.license_type,
                attribution_required=(
                    result.attribution_required
                ),
                attribution_text=(
                    result.attribution_text
                ),
                duration_seconds=(
                    result.duration_seconds
                ),
                resolution=result.resolution,
                aspect_ratio=result.aspect_ratio,
                width=result.width,
                height=result.height,
                quality=result.quality,
                score=result.score,
                metadata=dict(result.metadata),
            )
            for result in stock_results[:limit]
        ]