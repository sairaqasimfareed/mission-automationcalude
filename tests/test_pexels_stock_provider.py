from __future__ import annotations

import json

from src.models.provider_profile import ProviderCategory, ProviderProfile
from src.providers.pexels_stock_provider import PexelsStockProvider
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
    profile_id="pexels",
    display_name="Pexels",
    provider_name="pexels",
    category=ProviderCategory.STOCK_VIDEO,
)

canned_response = HttpTransportResponse(
    status_code=200,
    headers={},
    content=json.dumps(
        {
            "page": 1,
            "per_page": 15,
            "total_results": 1,
            "next_page": "https://api.pexels.com/videos/search?page=2",
            "videos": [
                {
                    "id": 12345,
                    "url": "https://www.pexels.com/video/12345/",
                    "image": "https://images.pexels.com/thumb.jpg",
                    "duration": 20,
                    "video_files": [
                        {
                            "link": "https://cdn.pexels.com/sd.mp4",
                            "width": 640,
                            "height": 360,
                            "file_type": "video/mp4",
                        },
                        {
                            "link": "https://cdn.pexels.com/hd.mp4",
                            "width": 1920,
                            "height": 1080,
                            "file_type": "video/mp4",
                        },
                    ],
                }
            ],
        }
    ).encode(),
)

transport = _RecordingTransport(canned_response)

provider = PexelsStockProvider(
    profile=profile, api_key="real-pexels-key", transport=transport
)

assert provider.provider_name == "pexels"
assert provider.health_check() is True

response = provider.search(StockSearchRequest(query="mountains", per_page=5))

assert response.provider == "pexels"
assert response.has_more is True
assert response.total_results == 1
assert len(response.results) == 1

result = response.results[0]
# Must pick the highest-width video_files entry (1920), not the first one.
assert result.file_url == "https://cdn.pexels.com/hd.mp4"
assert result.width == 1920
assert result.height == 1080
assert result.provider_asset_id == "12345"
assert result.title == "mountains"
assert result.duration_seconds == 20.0

sent = transport.received_requests[0]
assert sent.method == "GET"
assert sent.headers["Authorization"] == "real-pexels-key"
assert sent.params == {"query": "mountains", "page": "1", "per_page": "5"}

print("PexelsStockProvider tests completed successfully.")
