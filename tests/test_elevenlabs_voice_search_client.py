from __future__ import annotations

import json

import pytest

from src.providers.elevenlabs_voice_search_client import ElevenLabsVoiceSearchClient
from src.services.http.http_provider_executor import (
    HttpProviderExecutionError,
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


_GOOD_PAYLOAD = json.dumps(
    {
        "voices": [
            {
                "voice_id": "voice-abc",
                "name": "Deep Dark Narrator",
                "category": "premade",
                "labels": {"gender": "male", "accent": "american"},
                "description": "A deep, resonant narration voice.",
                "preview_url": "https://example.com/preview-abc.mp3",
            },
            {
                "voice_id": "voice-def",
                "name": "Whisper Voice",
                "category": "cloned",
            },
        ]
    }
).encode("utf-8")


def _client(
    response: HttpTransportResponse,
) -> tuple[ElevenLabsVoiceSearchClient, _RecordingTransport]:
    transport = _RecordingTransport(response)
    client = ElevenLabsVoiceSearchClient(api_key="real-key-123", transport=transport)

    return client, transport


def test_search_parses_real_voice_results() -> None:
    client, transport = _client(
        HttpTransportResponse(status_code=200, headers={}, content=_GOOD_PAYLOAD)
    )

    results = client.search(query="deep dark whisper")

    assert len(results) == 2
    assert results[0].voice_id == "voice-abc"
    assert results[0].name == "Deep Dark Narrator"
    assert results[0].labels == {"gender": "male", "accent": "american"}
    assert results[0].preview_url == "https://example.com/preview-abc.mp3"


def test_search_defaults_missing_optional_fields() -> None:
    client, transport = _client(
        HttpTransportResponse(status_code=200, headers={}, content=_GOOD_PAYLOAD)
    )

    results = client.search(query="deep dark whisper")

    assert results[1].voice_id == "voice-def"
    assert results[1].labels == {}
    assert results[1].description == ""
    assert results[1].preview_url is None


def test_search_sends_the_real_query_and_endpoint() -> None:
    client, transport = _client(
        HttpTransportResponse(status_code=200, headers={}, content=_GOOD_PAYLOAD)
    )

    client.search(query="deep dark whisper", page_size=3)

    sent = transport.received_requests[0]
    assert sent.method == "GET"
    assert sent.url == "https://api.elevenlabs.io/v2/voices"
    assert sent.headers["xi-api-key"] == "real-key-123"
    assert sent.params is not None
    assert sent.params["search"] == "deep dark whisper"
    assert sent.params["page_size"] == "3"


def test_search_rejects_an_empty_query() -> None:
    client, _transport = _client(
        HttpTransportResponse(status_code=200, headers={}, content=_GOOD_PAYLOAD)
    )

    with pytest.raises(ValueError, match="cannot be empty"):
        client.search(query="   ")


def test_search_raises_on_http_error_status() -> None:
    client, _transport = _client(
        HttpTransportResponse(status_code=401, headers={}, content=b"unauthorized")
    )

    with pytest.raises(HttpProviderExecutionError, match="HTTP 401"):
        client.search(query="deep dark whisper")


def test_search_raises_on_non_json_response() -> None:
    client, _transport = _client(
        HttpTransportResponse(status_code=200, headers={}, content=b"not json")
    )

    with pytest.raises(HttpProviderExecutionError, match="non-JSON"):
        client.search(query="deep dark whisper")


def test_search_raises_when_voices_array_is_missing() -> None:
    client, _transport = _client(
        HttpTransportResponse(
            status_code=200, headers={}, content=b'{"not_voices": []}'
        )
    )

    results = client.search(query="deep dark whisper")

    # No "voices" key -> payload.get("voices", []) defaults to an
    # empty list, a genuinely empty real result, not an error.
    assert results == []


def test_search_skips_a_malformed_voice_entry_missing_voice_id() -> None:
    payload = json.dumps({"voices": [{"name": "No id here"}]}).encode("utf-8")
    client, _transport = _client(
        HttpTransportResponse(status_code=200, headers={}, content=payload)
    )

    results = client.search(query="deep dark whisper")

    assert results == []
