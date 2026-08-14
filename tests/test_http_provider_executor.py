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
from src.services.http.http_provider_executor import (
    HttpAdapterTemplateError,
    HttpProviderExecutionError,
    HttpProviderExecutor,
    HttpTransportResponse,
    PreparedHttpRequest,
)


class _RecordingTransport:
    """Fake Transport that records the request and returns a canned response."""

    def __init__(self, response: HttpTransportResponse) -> None:
        self.response = response
        self.received_requests: list[PreparedHttpRequest] = []

    def __call__(self, request: PreparedHttpRequest) -> HttpTransportResponse:
        self.received_requests.append(request)

        return self.response


# --- execute(): placeholder rendering, auth placement, error handling ---

binary_config = HttpAdapterConfig(
    http_method=HttpMethod.POST,
    url_template="https://api.example.com/tts/{voice}",
    headers={"xi-api-key": "{api_key}"},
    json_body_template={"text": "{text}"},
    response_mode=HttpResponseMode.BINARY_FILE,
)

transport = _RecordingTransport(
    HttpTransportResponse(status_code=200, headers={}, content=b"fake-audio-bytes")
)
executor = HttpProviderExecutor(transport=transport)

response = executor.execute(
    binary_config,
    placeholders={"text": "hello world", "voice": "narrator-1"},
    api_key="secret-key-123",
    timeout_seconds=30.0,
)

assert response.content == b"fake-audio-bytes"
assert len(transport.received_requests) == 1

sent = transport.received_requests[0]
assert sent.url == "https://api.example.com/tts/narrator-1"
assert sent.headers["xi-api-key"] == "secret-key-123"
assert sent.json_body == {"text": "hello world"}
assert sent.method == "POST"

# Unknown placeholder raises a typed, actionable error rather than KeyError.
bad_config = HttpAdapterConfig(
    url_template="https://api.example.com/tts/{unknown_field}",
    response_mode=HttpResponseMode.BINARY_FILE,
)

try:
    executor.execute(bad_config, placeholders={}, api_key="k")
except HttpAdapterTemplateError as error:
    assert "unknown_field" in str(error)
    print("Unknown placeholder correctly rejected:", error)
else:
    raise AssertionError("Expected HttpAdapterTemplateError.")

# A non-2xx response raises HttpProviderExecutionError.
error_transport = _RecordingTransport(
    HttpTransportResponse(status_code=500, headers={}, content=b"server error")
)
error_executor = HttpProviderExecutor(transport=error_transport)

try:
    error_executor.execute(
        binary_config, placeholders={"text": "x", "voice": "y"}, api_key="k"
    )
except HttpProviderExecutionError as error:
    print("HTTP 500 correctly raised:", error)
else:
    raise AssertionError("Expected HttpProviderExecutionError.")


# --- extract_binary_file(): writes response bytes to a new file ---

with TemporaryDirectory() as temp_dir:
    path_str = executor.extract_binary_file(
        response,
        destination_directory=temp_dir,
        default_extension=".mp3",
        config=binary_config,
    )
    path = Path(path_str)

    assert path.exists()
    assert path.suffix == ".mp3"
    assert path.read_bytes() == b"fake-audio-bytes"


# --- extract_json_file_url() + download_to_file(): JSON-wrapped-URL mode ---

json_url_config = HttpAdapterConfig(
    url_template="https://api.example.com/generate",
    response_mode=HttpResponseMode.JSON_FILE_URL,
    response_file_url_path="data.audio_url",
)

json_response = HttpTransportResponse(
    status_code=200,
    headers={},
    content=json.dumps(
        {"data": {"audio_url": "https://cdn.example.com/a.mp3"}}
    ).encode(),
)

file_url = executor.extract_json_file_url(json_response, json_url_config)
assert file_url == "https://cdn.example.com/a.mp3"

download_transport = _RecordingTransport(
    HttpTransportResponse(status_code=200, headers={}, content=b"downloaded-bytes")
)
download_executor = HttpProviderExecutor(transport=download_transport)

with TemporaryDirectory() as temp_dir:
    downloaded_path = Path(
        download_executor.download_to_file(
            file_url,
            destination_directory=temp_dir,
            default_extension=".mp3",
        )
    )
    assert downloaded_path.read_bytes() == b"downloaded-bytes"
    assert download_transport.received_requests[0].url == file_url
    assert download_transport.received_requests[0].method == "GET"

# Missing response_file_url_path segment raises with the failing segment named.
try:
    executor.extract_json_file_url(
        HttpTransportResponse(
            status_code=200,
            headers={},
            content=json.dumps({"data": {}}).encode(),
        ),
        json_url_config,
    )
except HttpAdapterTemplateError as error:
    print("Missing JSON path correctly rejected:", error)
else:
    raise AssertionError("Expected HttpAdapterTemplateError.")


# --- extract_json_result_list(): stock-search-shaped JSON list mapping ---

list_config = HttpAdapterConfig(
    url_template="https://api.example.com/search?query={query}",
    http_method=HttpMethod.GET,
    response_mode=HttpResponseMode.JSON_RESULT_LIST,
    response_list_path="videos",
    response_field_mapping=StockResultFieldMapping(
        file_url_path="video_files.0.link",
        title_path="title",
        width_path="video_files.0.width",
        height_path="video_files.0.height",
        duration_seconds_path="duration",
    ),
)

list_response = HttpTransportResponse(
    status_code=200,
    headers={},
    content=json.dumps(
        {
            "videos": [
                {
                    "title": "Mountain sunrise",
                    "duration": 12.5,
                    "video_files": [
                        {
                            "link": "https://cdn.example.com/v1.mp4",
                            "width": 1920,
                            "height": 1080,
                        }
                    ],
                },
                {
                    "duration": 8,
                    "video_files": [
                        {
                            "link": "https://cdn.example.com/v2.mp4",
                            "width": 1280,
                            "height": 720,
                        }
                    ],
                },
            ]
        }
    ).encode(),
)

results = executor.extract_json_result_list(
    list_response, list_config, provider_name="fake_stock", query="mountains"
)

assert len(results) == 2
assert results[0].provider == "fake_stock"
assert results[0].provider_asset_id == "0"
assert results[0].title == "Mountain sunrise"
assert results[0].file_url == "https://cdn.example.com/v1.mp4"
assert results[0].width == 1920
assert results[0].height == 1080
assert results[0].duration_seconds == 12.5

# Second item has no "title" field -> falls back to the search query.
assert results[1].title == "mountains"
assert results[1].provider_asset_id == "1"

print("HttpProviderExecutor tests completed successfully.")
