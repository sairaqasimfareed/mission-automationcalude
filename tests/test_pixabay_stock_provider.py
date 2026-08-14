from __future__ import annotations

import json

from src.models.provider_profile import ProviderCategory, ProviderProfile
from src.providers.pixabay_stock_provider import PixabayStockProvider
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
    profile_id="pixabay",
    display_name="Pixabay",
    provider_name="pixabay",
    category=ProviderCategory.STOCK_VIDEO,
)

canned_response = HttpTransportResponse(
    status_code=200,
    headers={},
    content=json.dumps(
        {
            "total": 1,
            "totalHits": 1,
            "hits": [
                {
                    "id": 999,
                    "pageURL": "https://pixabay.com/videos/999",
                    "tags": "forest, mist, morning",
                    "duration": 15,
                    "videos": {
                        "large": {
                            "url": "https://cdn.pixabay.com/large.mp4",
                            "width": 1920,
                            "height": 1080,
                        },
                        "medium": {
                            "url": "https://cdn.pixabay.com/medium.mp4",
                            "width": 1280,
                            "height": 720,
                        },
                    },
                },
                {
                    "id": 1000,
                    "pageURL": "https://pixabay.com/videos/1000",
                    "tags": "",
                    "duration": 10,
                    "videos": {
                        "tiny": {
                            "url": "https://cdn.pixabay.com/tiny.mp4",
                            "width": 320,
                            "height": 180,
                        }
                    },
                },
            ],
        }
    ).encode(),
)

transport = _RecordingTransport(canned_response)

provider = PixabayStockProvider(
    profile=profile, api_key="real-pixabay-key", transport=transport
)

assert provider.provider_name == "pixabay"
assert provider.health_check() is True

# per_page below Pixabay's minimum (3) must be clamped up, not sent as-is.
response = provider.search(StockSearchRequest(query="forest", per_page=1))

assert len(response.results) == 2

first = response.results[0]
# Must prefer "large" over "medium" - the quality-tier order, not dict order.
assert first.file_url == "https://cdn.pixabay.com/large.mp4"
assert first.width == 1920
assert first.title == "forest, mist, morning"

second = response.results[1]
# Falls through to "tiny" when nothing better is present.
assert second.file_url == "https://cdn.pixabay.com/tiny.mp4"
# Empty tags string falls back to the search query.
assert second.title == "forest"

sent = transport.received_requests[0]
assert sent.params is not None
assert sent.params["key"] == "real-pixabay-key"
assert sent.params["q"] == "forest"
assert sent.params["per_page"] == "3"
assert "Authorization" not in sent.headers

print("PixabayStockProvider tests completed successfully.")
