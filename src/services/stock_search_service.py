from __future__ import annotations

from typing import Protocol

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel


class StockSearchRequest(MissionBaseModel):
    """Provider-independent stock-footage search request."""

    query: str = Field(
        min_length=1,
        max_length=500,
    )

    page: int = Field(
        default=1,
        ge=1,
    )

    per_page: int = Field(
        default=15,
        ge=1,
        le=100,
    )

    orientation: str | None = None

    minimum_duration_seconds: float | None = Field(
        default=None,
        ge=0.0,
    )

    maximum_duration_seconds: float | None = Field(
        default=None,
        ge=0.0,
    )

    minimum_width: int | None = Field(
        default=None,
        ge=1,
    )

    minimum_height: int | None = Field(
        default=None,
        ge=1,
    )

    @field_validator("query")
    @classmethod
    def clean_query(
        cls,
        value: str,
    ) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError(
                "Stock search query cannot be empty."
            )

        return cleaned


class StockSearchResult(MissionBaseModel):
    """One normalized stock-footage search result."""

    provider: str
    provider_asset_id: str

    title: str
    page_url: str | None = None

    file_url: str
    thumbnail_url: str | None = None

    license_type: str = "unknown"
    attribution_required: bool = False
    attribution_text: str | None = None

    duration_seconds: float = Field(
        default=0.0,
        ge=0.0,
    )

    width: int | None = Field(
        default=None,
        ge=1,
    )

    height: int | None = Field(
        default=None,
        ge=1,
    )

    resolution: str | None = None
    aspect_ratio: str | None = None

    quality: str | None = None
    file_type: str = "video/mp4"

    score: float = Field(
        default=0.0,
        ge=0.0,
    )

    metadata: dict[str, str] = Field(
        default_factory=dict,
    )


class StockSearchResponse(MissionBaseModel):
    """Normalized response from one stock provider."""

    provider: str
    query: str

    results: list[StockSearchResult] = Field(
        default_factory=list,
    )

    page: int = Field(
        default=1,
        ge=1,
    )

    per_page: int = Field(
        default=15,
        ge=1,
    )

    total_results: int | None = Field(
        default=None,
        ge=0,
    )

    has_more: bool = False


class StockProviderAdapter(Protocol):
    """Contract implemented by each stock API adapter."""

    @property
    def provider_name(self) -> str:
        """Return the provider display name."""
        ...

    def health_check(self) -> bool:
        """Return whether the provider is usable."""
        ...

    def search(
        self,
        request: StockSearchRequest,
    ) -> StockSearchResponse:
        """Search the provider for stock footage."""
        ...


class DryRunStockProvider:
    """Deterministic stock provider for tests and development."""

    @property
    def provider_name(self) -> str:
        return "Dry Run Stock"

    def health_check(self) -> bool:
        return True

    def search(
        self,
        request: StockSearchRequest,
    ) -> StockSearchResponse:
        result = StockSearchResult(
            provider=self.provider_name,
            provider_asset_id="dry-run-video-001",
            title=request.query,
            page_url=(
                "https://example.com/stock/"
                "dry-run-video-001"
            ),
            file_url=(
                "https://example.com/videos/"
                "dry-run-video-001.mp4"
            ),
            thumbnail_url=(
                "https://example.com/thumbnails/"
                "dry-run-video-001.jpg"
            ),
            license_type="royalty_free",
            attribution_required=False,
            duration_seconds=8.0,
            width=1920,
            height=1080,
            resolution="1920x1080",
            aspect_ratio="16:9",
            quality="hd",
            score=1.0,
            metadata={
                "dry_run": "true",
            },
        )

        return StockSearchResponse(
            provider=self.provider_name,
            query=request.query,
            results=[
                result,
            ],
            page=request.page,
            per_page=request.per_page,
            total_results=1,
            has_more=False,
        )


class StockSearchService:
    """Searches one or more registered stock providers."""

    def __init__(
        self,
        providers: list[StockProviderAdapter] | None = None,
    ) -> None:
        self.providers = providers or [
            DryRunStockProvider(),
        ]

    def search(
        self,
        request: StockSearchRequest,
    ) -> list[StockSearchResult]:
        """Search all healthy providers and combine results."""

        combined_results: list[StockSearchResult] = []

        for provider in self.providers:
            if not provider.health_check():
                continue

            response = provider.search(request)

            combined_results.extend(
                response.results
            )

        return sorted(
            combined_results,
            key=lambda result: result.score,
            reverse=True,
        )

    def available_providers(self) -> list[str]:
        """Return names of currently healthy providers."""

        return [
            provider.provider_name
            for provider in self.providers
            if provider.health_check()
        ]