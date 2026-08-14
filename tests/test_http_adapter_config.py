from __future__ import annotations

from src.models.http_adapter_config import (
    HttpAdapterConfig,
    HttpMethod,
    HttpResponseMode,
    StockResultFieldMapping,
)

binary_config = HttpAdapterConfig(
    url_template="https://api.elevenlabs.io/v1/text-to-speech/{voice}",
    response_mode=HttpResponseMode.BINARY_FILE,
    headers={"xi-api-key": "{api_key}"},
    json_body_template={"text": "{text}"},
)

assert binary_config.http_method == HttpMethod.POST
assert binary_config.response_file_url_path is None
assert binary_config.response_list_path is None

# JSON_FILE_URL requires response_file_url_path.
try:
    HttpAdapterConfig(
        url_template="https://example.com/generate",
        response_mode=HttpResponseMode.JSON_FILE_URL,
    )
except ValueError:
    print("JSON_FILE_URL without response_file_url_path correctly rejected.")
else:
    raise AssertionError("Expected a ValueError.")

json_file_url_config = HttpAdapterConfig(
    url_template="https://example.com/generate",
    response_mode=HttpResponseMode.JSON_FILE_URL,
    response_file_url_path="data.audio_url",
)
assert json_file_url_config.response_file_url_path == "data.audio_url"

# JSON_RESULT_LIST requires both response_list_path and response_field_mapping.
try:
    HttpAdapterConfig(
        url_template="https://api.pexels.com/videos/search?query={query}",
        http_method=HttpMethod.GET,
        response_mode=HttpResponseMode.JSON_RESULT_LIST,
        response_list_path="videos",
    )
except ValueError:
    print("JSON_RESULT_LIST without response_field_mapping correctly rejected.")
else:
    raise AssertionError("Expected a ValueError.")

list_config = HttpAdapterConfig(
    url_template="https://api.pexels.com/videos/search?query={query}",
    http_method=HttpMethod.GET,
    response_mode=HttpResponseMode.JSON_RESULT_LIST,
    response_list_path="videos",
    response_field_mapping=StockResultFieldMapping(
        file_url_path="video_files.0.link",
        width_path="video_files.0.width",
    ),
)
assert list_config.response_field_mapping is not None
assert list_config.response_field_mapping.file_url_path == "video_files.0.link"

# Round-trips through JSON exactly like JsonProviderProfileRepository does.
dumped = list_config.model_dump_json()
reloaded = HttpAdapterConfig.model_validate_json(dumped)
assert reloaded.response_field_mapping is not None
assert reloaded.response_field_mapping.width_path == "video_files.0.width"

print("HttpAdapterConfig tests completed successfully.")
