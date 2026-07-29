from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class StockSearchResult:
    """
    Represents one stock footage search result.

    This is provider-independent.
    """

    provider: str
    title: str
    file_url: str
    thumbnail_url: str | None = None
    license_type: str = "unknown"
    duration_seconds: int = 0
    resolution: str = "1920x1080"


class StockSearchService:
    """
    Central stock footage search service.

    Future providers:
        - Pexels
        - Pixabay
        - Storyblocks
        - Envato
    """

    def search(
        self,
        query: str,
    ) -> list[StockSearchResult]:
        """
        Dry-run implementation.

        Future versions will search real APIs.
        """

        return [
            StockSearchResult(
                provider="Dry Run",
                title=query,
                file_url="https://example.com/demo.mp4",
                thumbnail_url=None,
                license_type="royalty_free",
                duration_seconds=8,
            )
        ]