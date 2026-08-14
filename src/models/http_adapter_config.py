from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class HttpMethod(str, Enum):
    """HTTP method used to call a no-code provider endpoint."""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"


class HttpResponseMode(str, Enum):
    """How a no-code provider's HTTP response should be interpreted."""

    BINARY_FILE = "binary_file"
    JSON_FILE_URL = "json_file_url"
    JSON_RESULT_LIST = "json_result_list"


class StockResultFieldMapping(BaseModel):
    """
    Dot-path field mapping applied to each element of a search-result
    array, for JSON_RESULT_LIST responses (stock video/image search).

    Dot-path segments that parse as integers are treated as list
    indices (e.g. "video_files.0.link"), otherwise as dict keys.
    """

    file_url_path: str = Field(min_length=1)

    provider_asset_id_path: str | None = None
    title_path: str | None = None
    page_url_path: str | None = None
    thumbnail_url_path: str | None = None
    duration_seconds_path: str | None = None
    width_path: str | None = None
    height_path: str | None = None

    file_type: str = "video/mp4"


class HttpAdapterConfig(BaseModel):
    """
    No-code HTTP provider configuration.

    Lets a brand-new provider be added from the frontend without new
    Python code: a request template (method, URL, headers, query
    params, JSON body) rendered with category-specific placeholders,
    and a response interpretation mode. Stored as a first-class typed
    field on ProviderProfile rather than folded into its free-form
    metadata dict, since a request-body template is itself nested
    structure that a str-only dict can't hold cleanly.
    """

    schema_version: str = "1.0"

    http_method: HttpMethod = HttpMethod.POST

    url_template: str = Field(min_length=1)

    headers: dict[str, str] = Field(default_factory=dict)
    query_params: dict[str, str] = Field(default_factory=dict)
    json_body_template: dict[str, Any] | None = None

    response_mode: HttpResponseMode

    response_file_url_path: str | None = None
    response_binary_file_extension: str | None = None
    response_list_path: str | None = None
    response_field_mapping: StockResultFieldMapping | None = None

    @model_validator(mode="after")
    def validate_response_mode_fields(self) -> HttpAdapterConfig:
        if self.response_mode == HttpResponseMode.JSON_FILE_URL:
            if not self.response_file_url_path:
                raise ValueError(
                    "response_file_url_path is required when "
                    "response_mode is json_file_url."
                )

        if self.response_mode == HttpResponseMode.JSON_RESULT_LIST:
            if not self.response_list_path:
                raise ValueError(
                    "response_list_path is required when "
                    "response_mode is json_result_list."
                )

            if self.response_field_mapping is None:
                raise ValueError(
                    "response_field_mapping is required when "
                    "response_mode is json_result_list."
                )

        return self
