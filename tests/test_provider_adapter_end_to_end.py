from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from src.models.http_adapter_config import (
    HttpAdapterConfig,
    HttpMethod,
    HttpResponseMode,
    StockResultFieldMapping,
)
from src.models.provider_profile import (
    ProviderCategory,
    ProviderHealthStatus,
    ProviderProfile,
)
from src.providers.elevenlabs_voice_provider import ElevenLabsVoiceProvider
from src.providers.http.generic_http_stock_provider import GenericHttpStockProvider
from src.services.factory.provider_adapter_factory import ProviderAdapterFactory
from src.services.http.http_provider_executor import (
    HttpProviderExecutor,
    HttpTransportResponse,
    PreparedHttpRequest,
)
from src.services.secrets.provider_secret_manager import (
    InMemorySecretStore,
    ProviderSecretManager,
)
from src.services.stock_search_service import StockSearchRequest

# Proves ProviderProfile -> ProviderAdapterFactory -> real adapter -> the
# category interface the pipeline actually calls, end to end, for one coded
# adapter (ElevenLabs voice) and one generic no-code adapter (a made-up
# stock provider configured entirely through HttpAdapterConfig) - with no
# real network access anywhere in the chain.

secret_store = InMemorySecretStore()
secret_manager = ProviderSecretManager(secret_store=secret_store)
factory = ProviderAdapterFactory(secret_manager=secret_manager)

voice_secret = secret_manager.create_secret(
    profile_id="elevenlabs-e2e", secret_value="real-elevenlabs-key"
)

voice_profile = ProviderProfile(
    profile_id="elevenlabs-e2e",
    display_name="ElevenLabs (e2e)",
    provider_name="elevenlabs",
    category=ProviderCategory.VOICE,
    enabled=True,
    health_status=ProviderHealthStatus.HEALTHY,
    secret_reference=voice_secret.secret_reference,
)

stock_secret = secret_manager.create_secret(
    profile_id="custom-stock-e2e", secret_value="real-custom-stock-key"
)

stock_profile = ProviderProfile(
    profile_id="custom-stock-e2e",
    display_name="Custom Stock (e2e)",
    provider_name="my-totally-new-stock-vendor",
    category=ProviderCategory.STOCK_VIDEO,
    enabled=True,
    health_status=ProviderHealthStatus.HEALTHY,
    secret_reference=stock_secret.secret_reference,
    http_adapter_config=HttpAdapterConfig(
        http_method=HttpMethod.GET,
        url_template="https://api.newstockvendor.example.com/v1/search",
        headers={"X-Api-Key": "{api_key}"},
        query_params={"q": "{query}"},
        response_mode=HttpResponseMode.JSON_RESULT_LIST,
        response_list_path="items",
        response_field_mapping=StockResultFieldMapping(
            file_url_path="download_url",
            title_path="caption",
            width_path="dimensions.width",
            height_path="dimensions.height",
        ),
    ),
)

report = factory.build([voice_profile, stock_profile])

assert report.warnings == []
assert len(report.voice_providers) == 1
assert len(report.stock_video_providers) == 1

voice_adapter = report.voice_providers[0]
stock_adapter = report.stock_video_providers[0]

assert isinstance(voice_adapter, ElevenLabsVoiceProvider)
assert isinstance(stock_adapter, GenericHttpStockProvider)

# Fake transports stand in for the real ElevenLabs API and the brand-new
# vendor's API - no requests library call happens anywhere below.
voice_requests: list[PreparedHttpRequest] = []


def _fake_voice_transport(request: PreparedHttpRequest) -> HttpTransportResponse:
    voice_requests.append(request)

    return HttpTransportResponse(
        status_code=200, headers={}, content=b"fake-elevenlabs-audio-bytes"
    )


stock_requests: list[PreparedHttpRequest] = []


def _fake_stock_transport(request: PreparedHttpRequest) -> HttpTransportResponse:
    stock_requests.append(request)

    return HttpTransportResponse(
        status_code=200,
        headers={},
        content=json.dumps(
            {
                "items": [
                    {
                        "download_url": "https://cdn.newstockvendor.example.com/clip.mp4",
                        "caption": "A brand new stock clip",
                        "dimensions": {"width": 1920, "height": 1080},
                    }
                ]
            }
        ).encode(),
    )


assert voice_profile.secret_reference is not None
assert stock_profile.secret_reference is not None

with TemporaryDirectory() as temp_dir:
    voice_adapter_with_fake_transport = ElevenLabsVoiceProvider(
        profile=voice_profile,
        api_key=secret_manager.resolve_secret(voice_profile.secret_reference),
        transport=_fake_voice_transport,
        output_directory=temp_dir,
    )

    voice_path = Path(
        voice_adapter_with_fake_transport.generate_voice(
            "This is a fully wired end-to-end test.", "narrator-voice-id"
        )
    )

    assert voice_path.exists()
    assert voice_path.read_bytes() == b"fake-elevenlabs-audio-bytes"

stock_adapter_with_fake_transport = GenericHttpStockProvider(
    profile=stock_profile,
    api_key=secret_manager.resolve_secret(stock_profile.secret_reference),
    executor=HttpProviderExecutor(transport=_fake_stock_transport),
)

search_response = stock_adapter_with_fake_transport.search(
    StockSearchRequest(query="brand new clips")
)

assert len(search_response.results) == 1
result = search_response.results[0]
assert result.file_url == "https://cdn.newstockvendor.example.com/clip.mp4"
assert result.title == "A brand new stock clip"
assert result.width == 1920
assert result.height == 1080

assert voice_requests[0].headers["xi-api-key"] == "real-elevenlabs-key"
assert stock_requests[0].headers["X-Api-Key"] == "real-custom-stock-key"
assert stock_requests[0].params == {"q": "brand new clips"}

print("Voice request URL:", voice_requests[0].url)
print("Stock request URL:", stock_requests[0].url)
print("PROVIDER ADAPTER END-TO-END ASSERTIONS PASSED (no real network calls)")
