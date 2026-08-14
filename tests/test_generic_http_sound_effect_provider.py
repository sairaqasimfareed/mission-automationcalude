from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from src.models.http_adapter_config import HttpAdapterConfig, HttpResponseMode
from src.models.provider_profile import ProviderCategory, ProviderProfile
from src.providers.http.generic_http_sound_effect_provider import (
    GenericHttpSoundEffectProvider,
)
from src.services.http.http_provider_executor import (
    HttpProviderExecutor,
    HttpTransportResponse,
    PreparedHttpRequest,
)


class _RecordingTransport:
    def __init__(self, response: HttpTransportResponse) -> None:
        self.response = response
        self.received_requests: list[PreparedHttpRequest] = []

    def __call__(self, request: PreparedHttpRequest) -> HttpTransportResponse:
        self.received_requests.append(request)

        return self.response


profile = ProviderProfile(
    profile_id="custom-sfx",
    display_name="Custom SFX",
    provider_name="my-custom-sfx",
    category=ProviderCategory.SOUND_EFFECTS,
    http_adapter_config=HttpAdapterConfig(
        url_template="https://api.example.com/sfx",
        headers={"Authorization": "Bearer {api_key}"},
        json_body_template={"prompt": "{library_query}"},
        response_mode=HttpResponseMode.BINARY_FILE,
    ),
)

transport = _RecordingTransport(
    HttpTransportResponse(status_code=200, headers={}, content=b"fake-sfx-bytes")
)

with TemporaryDirectory() as temp_dir:
    provider = GenericHttpSoundEffectProvider(
        profile=profile,
        api_key="test-key",
        executor=HttpProviderExecutor(transport=transport),
        output_directory=temp_dir,
    )

    assert provider.provider_name == "my-custom-sfx"
    assert provider.health_check() is True

    path = Path(provider.generate_sound_effect(library_query="wooden door creak"))

    assert path.exists()
    assert path.read_bytes() == b"fake-sfx-bytes"

    sent = transport.received_requests[0]
    assert sent.json_body == {"prompt": "wooden door creak"}

print("GenericHttpSoundEffectProvider tests completed successfully.")
