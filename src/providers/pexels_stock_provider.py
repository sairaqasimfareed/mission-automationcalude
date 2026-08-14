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

_DEFAULT_BASE_URL = "https://api.pexels.com"


class PexelsStockProvider:
    """
    Real Pexels video search adapter.

    Calls GET /videos/search with the API key in a plain Authorization
    header (Pexels does not use a "Bearer" prefix), and picks the
    highest-width entry from each result's video_files list as the
    best-quality download URL. Pexels has no true per-video "title"
    field, so the search query is used as the title. Coded from
    Pexels' documented Video API; not yet verified against a live
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
            "query": request.query,
            "page": str(request.page),
            "per_page": str(request.per_page),
        }

        if request.orientation:
            params["orientation"] = request.orientation

        prepared = PreparedHttpRequest(
            method="GET",
            url=f"{self._base_url}/videos/search",
            headers={"Authorization": self._api_key},
            params=params,
            timeout_seconds=float(self._profile.timeout_seconds),
        )

        response = self._transport(prepared)

        if response.status_code >= 400:
            raise HttpProviderExecutionError(
                f"Pexels search request failed with HTTP {response.status_code}."
            )

        try:
            payload = json.loads(response.content)
        except json.JSONDecodeError as error:
            raise HttpProviderExecutionError(
                f"Pexels search response was not valid JSON: {error}"
            ) from error

        results = [
            result
            for item in payload.get("videos", [])
            if (result := self._to_result(item, query=request.query)) is not None
        ]

        return StockSearchResponse(
            provider=self.provider_name,
            query=request.query,
            results=results,
            page=request.page,
            per_page=request.per_page,
            total_results=payload.get("total_results"),
            has_more=bool(payload.get("next_page")),
        )

    def _to_result(
        self, item: dict[str, Any], *, query: str
    ) -> StockSearchResult | None:
        video_files = item.get("video_files") or []

        if not video_files:
            return None

        best_file = max(video_files, key=lambda entry: entry.get("width") or 0)

        if not best_file.get("link"):
            return None

        return StockSearchResult(
            provider=self.provider_name,
            provider_asset_id=str(item.get("id", "")),
            title=query,
            page_url=item.get("url"),
            file_url=best_file["link"],
            thumbnail_url=item.get("image"),
            duration_seconds=float(item.get("duration", 0.0)),
            width=best_file.get("width"),
            height=best_file.get("height"),
            file_type=best_file.get("file_type", "video/mp4"),
        )
