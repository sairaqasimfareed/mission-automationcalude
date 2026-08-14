from __future__ import annotations

import json
from typing import Any

from src.models.provider_profile import ProviderProfile
from src.services.http.http_provider_executor import (
    HttpProviderExecutionError,
    PreparedHttpRequest,
    Transport,
    default_transport,
)
from src.services.stock_search_service import (
    StockSearchRequest,
    StockSearchResponse,
    StockSearchResult,
)

_DEFAULT_BASE_URL = "https://pixabay.com"
_QUALITY_TIERS = ("large", "medium", "small", "tiny")
_MINIMUM_PER_PAGE = 3


class PixabayStockProvider:
    """
    Real Pixabay video search adapter.

    Calls GET /api/videos/ with the API key as a query parameter (not
    a header, unlike Pexels), and picks the best available quality
    tier ("large" down to "tiny") from each hit's videos dict.
    Pixabay's minimum per_page is 3, so requests below that are
    clamped up rather than sent as an invalid request. Coded from
    Pixabay's documented Video API; not yet verified against a live
    account.
    """

    def __init__(
        self,
        *,
        profile: ProviderProfile,
        api_key: str,
        transport: Transport | None = None,
    ) -> None:
        self._profile = profile
        self._api_key = api_key
        self._transport = transport or default_transport
        self._base_url = (profile.base_url or _DEFAULT_BASE_URL).rstrip("/")

    @property
    def provider_name(self) -> str:
        return self._profile.provider_name

    def health_check(self) -> bool:
        return True

    def search(self, request: StockSearchRequest) -> StockSearchResponse:
        params = {
            "key": self._api_key,
            "q": request.query,
            "page": str(request.page),
            "per_page": str(max(request.per_page, _MINIMUM_PER_PAGE)),
        }

        prepared = PreparedHttpRequest(
            method="GET",
            url=f"{self._base_url}/api/videos/",
            params=params,
            timeout_seconds=float(self._profile.timeout_seconds),
        )

        response = self._transport(prepared)

        if response.status_code >= 400:
            raise HttpProviderExecutionError(
                f"Pixabay search request failed with HTTP {response.status_code}."
            )

        try:
            payload = json.loads(response.content)
        except json.JSONDecodeError as error:
            raise HttpProviderExecutionError(
                f"Pixabay search response was not valid JSON: {error}"
            ) from error

        results = [
            result
            for item in payload.get("hits", [])
            if (result := self._to_result(item, query=request.query)) is not None
        ]

        return StockSearchResponse(
            provider=self.provider_name,
            query=request.query,
            results=results,
            page=request.page,
            per_page=request.per_page,
            total_results=payload.get("totalHits"),
            has_more=False,
        )

    def _to_result(
        self, item: dict[str, Any], *, query: str
    ) -> StockSearchResult | None:
        videos = item.get("videos") or {}

        chosen: dict[str, Any] | None = None

        for tier in _QUALITY_TIERS:
            candidate = videos.get(tier)

            if candidate and candidate.get("url"):
                chosen = candidate

                break

        if chosen is None:
            return None

        return StockSearchResult(
            provider=self.provider_name,
            provider_asset_id=str(item.get("id", "")),
            title=item.get("tags") or query,
            page_url=item.get("pageURL"),
            file_url=chosen["url"],
            thumbnail_url=None,
            duration_seconds=float(item.get("duration", 0.0)),
            width=chosen.get("width"),
            height=chosen.get("height"),
            file_type="video/mp4",
        )
