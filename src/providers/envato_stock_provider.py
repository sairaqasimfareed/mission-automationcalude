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

_DEFAULT_BASE_URL = "https://api.envato.com"


class EnvatoStockProvider:
    """
    Best-effort Envato stock-video search adapter.

    Unlike Pexels/Pixabay, Envato does not publicly document a simple
    "search by keyword, get a direct download URL" API - its public
    API (api.envato.com) is primarily for license/purchase
    verification and catalog browsing, and Envato Elements assets
    normally require going through Envato's own licensed download
    flow rather than a plain GET on a file_url. This adapter is coded
    against a best-effort, Pexels/Pixabay-shaped assumption (a search
    endpoint returning a JSON array of items with a direct file URL)
    so the category is wired end to end, but it is NOT verified
    against a live Envato account and may need real changes once
    tested against one - confirm current Envato API capabilities
    (and whether direct download is even possible for your account
    type) before relying on this in production.
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
            "term": request.query,
            "page": str(request.page),
            "page_size": str(request.per_page),
        }

        prepared = PreparedHttpRequest(
            method="GET",
            url=f"{self._base_url}/v3/discovery/search/search/item",
            headers={"Authorization": f"Bearer {self._api_key}"},
            params=params,
            timeout_seconds=float(self._profile.timeout_seconds),
        )

        response = self._transport(prepared)

        if response.status_code >= 400:
            raise HttpProviderExecutionError(
                f"Envato search request failed with HTTP {response.status_code}."
            )

        try:
            payload = json.loads(response.content)
        except json.JSONDecodeError as error:
            raise HttpProviderExecutionError(
                f"Envato search response was not valid JSON: {error}"
            ) from error

        matches = payload.get("matches", payload.get("items", []))

        results = [
            result
            for item in matches
            if (result := self._to_result(item, query=request.query)) is not None
        ]

        return StockSearchResponse(
            provider=self.provider_name,
            query=request.query,
            results=results,
            page=request.page,
            per_page=request.per_page,
            total_results=payload.get("total_hits") or payload.get("total_items"),
            has_more=False,
        )

    def _to_result(
        self, item: dict[str, Any], *, query: str
    ) -> StockSearchResult | None:
        preview = item.get("previews", {}).get("video_preview", {}) or {}
        file_url = preview.get("video_url") or item.get("file_url")

        if not file_url:
            return None

        return StockSearchResult(
            provider=self.provider_name,
            provider_asset_id=str(item.get("id", "")),
            title=item.get("name") or query,
            page_url=item.get("url"),
            file_url=file_url,
            thumbnail_url=item.get("thumbnail_url"),
            duration_seconds=float(
                preview.get("length", {}).get("seconds", 0.0) or 0.0
            ),
            width=preview.get("width"),
            height=preview.get("height"),
            file_type="video/mp4",
            license_type="envato",
            attribution_required=False,
        )
