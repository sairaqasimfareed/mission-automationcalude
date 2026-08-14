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
from src.models.provider_profile import ProviderCategory, ProviderProfile
from src.providers.http.generic_http_voice_provider import GenericHttpVoiceProvider
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


# --- BINARY_FILE mode (ElevenLabs-shaped) ---

binary_profile = ProviderProfile(
    profile_id="custom-voice-binary",
    display_name="Custom Voice (binary)",
    provider_name="my-custom-tts",
    category=ProviderCategory.VOICE,
    http_adapter_config=HttpAdapterConfig(
        http_method=HttpMethod.POST,
        url_template="https://api.example.com/tts/{voice}",
        headers={"Authorization": "Bearer {api_key}"},
        json_body_template={"text": "{text}"},
        response_mode=HttpResponseMode.BINARY_FILE,
    ),
)

binary_transport = _RecordingTransport(
    HttpTransportResponse(status_code=200, headers={}, content=b"raw-audio-bytes")
)

with TemporaryDirectory() as temp_dir:
    provider = GenericHttpVoiceProvider(
        profile=binary_profile,
        api_key="test-key",
        executor=HttpProviderExecutor(transport=binary_transport),
        output_directory=temp_dir,
    )

    assert provider.provider_name == "my-custom-tts"
    assert provider.health_check() is True

    path = Path(provider.generate_voice("Hello there", "narrator-1"))

    assert path.exists()
    assert path.read_bytes() == b"raw-audio-bytes"

    sent = binary_transport.received_requests[0]
    assert sent.url == "https://api.example.com/tts/narrator-1"
    assert sent.headers["Authorization"] == "Bearer test-key"
    assert sent.json_body == {"text": "Hello there"}

print("BINARY_FILE voice provider case passed.")


# --- JSON_FILE_URL mode ---

json_url_profile = ProviderProfile(
    profile_id="custom-voice-json",
    display_name="Custom Voice (json url)",
    provider_name="my-json-tts",
    category=ProviderCategory.VOICE,
    http_adapter_config=HttpAdapterConfig(
        http_method=HttpMethod.POST,
        url_template="https://api.example.com/generate",
        json_body_template={"text": "{text}", "voice_id": "{voice}"},
        response_mode=HttpResponseMode.JSON_FILE_URL,
        response_file_url_path="result.audio_url",
    ),
)

first_response = HttpTransportResponse(
    status_code=200,
    headers={},
    content=json.dumps(
        {"result": {"audio_url": "https://cdn.example.com/out.mp3"}}
    ).encode(),
)
follow_up_response = HttpTransportResponse(
    status_code=200, headers={}, content=b"downloaded-audio"
)


class _TwoStepTransport:
    """First call returns the JSON wrapper; every call after returns audio bytes."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, request: PreparedHttpRequest) -> HttpTransportResponse:
        self.calls += 1

        return first_response if self.calls == 1 else follow_up_response


with TemporaryDirectory() as temp_dir:
    provider = GenericHttpVoiceProvider(
        profile=json_url_profile,
        api_key="test-key",
        executor=HttpProviderExecutor(transport=_TwoStepTransport()),
        output_directory=temp_dir,
    )

    path = Path(provider.generate_voice("Second line", "narrator-2"))

    assert path.exists()
    assert path.read_bytes() == b"downloaded-audio"

print("JSON_FILE_URL voice provider case passed.")


# --- construction guards ---

no_config_profile = ProviderProfile(
    profile_id="no-config",
    display_name="No Config",
    provider_name="whatever",
    category=ProviderCategory.VOICE,
)

try:
    GenericHttpVoiceProvider(profile=no_config_profile, api_key="k")
except ValueError as error:
    print("Missing http_adapter_config correctly rejected:", error)
else:
    raise AssertionError("Expected ValueError.")

wrong_mode_profile = ProviderProfile(
    profile_id="wrong-mode",
    display_name="Wrong Mode",
    provider_name="stock-shaped",
    category=ProviderCategory.VOICE,
    http_adapter_config=HttpAdapterConfig(
        url_template="https://api.example.com/search?query={query}",
        http_method=HttpMethod.GET,
        response_mode=HttpResponseMode.JSON_RESULT_LIST,
        response_list_path="items",
        response_field_mapping=StockResultFieldMapping(file_url_path="url"),
    ),
)

try:
    GenericHttpVoiceProvider(profile=wrong_mode_profile, api_key="k")
except ValueError as error:
    print(
        "json_result_list response_mode on a voice profile correctly rejected:", error
    )
else:
    raise AssertionError("Expected ValueError.")

print("GenericHttpVoiceProvider tests completed successfully.")
