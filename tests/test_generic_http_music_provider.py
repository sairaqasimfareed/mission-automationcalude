from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from src.models.http_adapter_config import HttpAdapterConfig, HttpResponseMode
from src.models.provider_profile import ProviderCategory, ProviderProfile
from src.providers.http.generic_http_music_provider import GenericHttpMusicProvider
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
    profile_id="custom-music",
    display_name="Custom Music",
    provider_name="my-custom-music",
    category=ProviderCategory.MUSIC,
    http_adapter_config=HttpAdapterConfig(
        url_template="https://api.example.com/music",
        headers={"Authorization": "Bearer {api_key}"},
        json_body_template={
            "prompt": "{library_query}",
            "duration_seconds": "{duration_seconds}",
        },
        response_mode=HttpResponseMode.BINARY_FILE,
    ),
)

transport = _RecordingTransport(
    HttpTransportResponse(status_code=200, headers={}, content=b"fake-music-bytes")
)

with TemporaryDirectory() as temp_dir:
    provider = GenericHttpMusicProvider(
        profile=profile,
        api_key="test-key",
        executor=HttpProviderExecutor(transport=transport),
        output_directory=temp_dir,
    )

    assert provider.provider_name == "my-custom-music"
    assert provider.health_check() is True

    path = Path(
        provider.generate_music(
            library_query="dark suspense drone", duration_seconds=40.0
        )
    )

    assert path.exists()
    assert path.read_bytes() == b"fake-music-bytes"

    sent = transport.received_requests[0]
    assert sent.json_body == {
        "prompt": "dark suspense drone",
        "duration_seconds": "40.0",
    }
    assert sent.headers["Authorization"] == "Bearer test-key"

print("GenericHttpMusicProvider tests completed successfully.")
