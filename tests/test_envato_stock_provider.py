from __future__ import annotations

import json

from src.models.provider_profile import ProviderCategory, ProviderProfile
from src.providers.envato_stock_provider import EnvatoStockProvider
from src.services.http.http_provider_executor import (
    HttpTransportResponse,
    PreparedHttpRequest,
)
from src.services.stock_search_service import StockSearchRequest


class _RecordingTransport:
    def __init__(self, response: HttpTransportResponse) -> None:
        self.response = response
        self.received_requests: list[PreparedHttpRequest] = []

    def __call__(self, request: PreparedHttpRequest) -> HttpTransportResponse:
        self.received_requests.append(request)

        return self.response


profile = ProviderProfile(
    profile_id="envato",
    display_name="Envato",
    provider_name="envato",
    category=ProviderCategory.STOCK_VIDEO,
)

canned_response = HttpTransportResponse(
    status_code=200,
    headers={},
    content=json.dumps(
        {
            "total_hits": 1,
            "matches": [
                {
                    "id": 42,
                    "name": "Ocean waves at sunset",
                    "url": "https://elements.envato.com/item-42",
                    "thumbnail_url": "https://envato.example.com/thumb.jpg",
                    "previews": {
                        "video_preview": {
                            "video_url": "https://envato.example.com/video.mp4",
                            "width": 1920,
                            "height": 1080,
                            "length": {"seconds": 12},
                        }
                    },
                }
            ],
        }
    ).encode(),
)

transport = _RecordingTransport(canned_response)

provider = EnvatoStockProvider(
    profile=profile, api_key="real-envato-key", transport=transport
)

assert provider.provider_name == "envato"
assert provider.health_check() is True

response = provider.search(StockSearchRequest(query="ocean waves"))

assert len(response.results) == 1

result = response.results[0]
assert result.file_url == "https://envato.example.com/video.mp4"
assert result.title == "Ocean waves at sunset"
assert result.provider_asset_id == "42"
assert result.width == 1920
assert result.duration_seconds == 12.0

sent = transport.received_requests[0]
assert sent.headers["Authorization"] == "Bearer real-envato-key"
assert sent.params == {"term": "ocean waves", "page": "1", "page_size": "15"}

# An item with no discoverable file URL must be skipped, not raise.
no_file_response = HttpTransportResponse(
    status_code=200,
    headers={},
    content=json.dumps({"matches": [{"id": 1, "name": "No preview"}]}).encode(),
)

no_file_provider = EnvatoStockProvider(
    profile=profile,
    api_key="real-envato-key",
    transport=_RecordingTransport(no_file_response),
)

empty_response = no_file_provider.search(StockSearchRequest(query="anything"))
assert empty_response.results == []

print("EnvatoStockProvider tests completed successfully.")
