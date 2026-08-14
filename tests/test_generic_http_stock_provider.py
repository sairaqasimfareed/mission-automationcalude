from __future__ import annotations

import json

from src.models.http_adapter_config import (
    HttpAdapterConfig,
    HttpMethod,
    HttpResponseMode,
    StockResultFieldMapping,
)
from src.models.provider_profile import ProviderCategory, ProviderProfile
from src.providers.http.generic_http_stock_provider import GenericHttpStockProvider
from src.services.http.http_provider_executor import (
    HttpProviderExecutor,
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
    profile_id="custom-stock",
    display_name="Custom Stock",
    provider_name="my-custom-stock",
    category=ProviderCategory.STOCK_VIDEO,
    http_adapter_config=HttpAdapterConfig(
        http_method=HttpMethod.GET,
        url_template="https://api.example.com/search",
        headers={"Authorization": "Bearer {api_key}"},
        query_params={"q": "{query}", "per_page": "{per_page}"},
        response_mode=HttpResponseMode.JSON_RESULT_LIST,
        response_list_path="results",
        response_field_mapping=StockResultFieldMapping(
            file_url_path="url",
            width_path="width",
            height_path="height",
        ),
    ),
)

transport = _RecordingTransport(
    HttpTransportResponse(
        status_code=200,
        headers={},
        content=json.dumps(
            {
                "results": [
                    {
                        "url": "https://cdn.example.com/clip1.mp4",
                        "width": 1920,
                        "height": 1080,
                    },
                    {
                        "url": "https://cdn.example.com/clip2.mp4",
                        "width": 1280,
                        "height": 720,
                    },
                ]
            }
        ).encode(),
    )
)

provider = GenericHttpStockProvider(
    profile=profile,
    api_key="test-key",
    executor=HttpProviderExecutor(transport=transport),
)

assert provider.provider_name == "my-custom-stock"
assert provider.health_check() is True

response = provider.search(StockSearchRequest(query="mountains", per_page=10))

assert response.provider == "my-custom-stock"
assert response.query == "mountains"
assert len(response.results) == 2
assert response.results[0].file_url == "https://cdn.example.com/clip1.mp4"
assert response.results[0].width == 1920

sent = transport.received_requests[0]
assert sent.params == {"q": "mountains", "per_page": "10"}
assert sent.headers["Authorization"] == "Bearer test-key"
assert sent.method == "GET"

print("GenericHttpStockProvider tests completed successfully.")
