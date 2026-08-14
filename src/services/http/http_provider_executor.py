from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

import requests

from src.models.http_adapter_config import HttpAdapterConfig
from src.services.stock_search_service import StockSearchResult

_DEFAULT_TIMEOUT_SECONDS = 60.0


class HttpProviderExecutionError(RuntimeError):
    """A no-code HTTP provider request failed."""


class HttpAdapterTemplateError(ValueError):
    """A no-code HTTP provider's template or response mapping is invalid."""


@dataclass(frozen=True, slots=True)
class PreparedHttpRequest:
    """One fully rendered HTTP request, ready to send."""

    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    params: dict[str, str] | None = None
    json_body: dict[str, Any] | None = None
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class HttpTransportResponse:
    """One HTTP response, normalized across transports."""

    status_code: int
    headers: dict[str, str]
    content: bytes


Transport = Callable[[PreparedHttpRequest], HttpTransportResponse]


def default_transport(request: PreparedHttpRequest) -> HttpTransportResponse:
    """
    Default Transport implementation, backed by the `requests` library.

    Public (not just HttpProviderExecutor's internal default) so coded
    vendor-specific adapters - which build their own PreparedHttpRequest
    directly rather than going through HttpAdapterConfig templating -
    can share the same real transport and the same injectable-fake
    pattern in tests.
    """

    try:
        response = requests.request(
            method=request.method,
            url=request.url,
            headers=request.headers or None,
            params=request.params,
            json=request.json_body,
            timeout=request.timeout_seconds,
        )
    except requests.exceptions.RequestException as error:
        raise HttpProviderExecutionError(
            f"HTTP request failed: {type(error).__name__}: {error}"
        ) from error

    return HttpTransportResponse(
        status_code=response.status_code,
        headers=dict(response.headers),
        content=response.content,
    )


class _MissingPlaceholderDict(dict[str, str]):
    """A dict whose missing keys raise a typed, actionable error."""

    def __missing__(self, key: str) -> str:
        raise HttpAdapterTemplateError(
            f"Unknown placeholder '{{{key}}}' in a no-code HTTP provider "
            "template. Check the configured URL/headers/query params/body "
            "against the placeholders available for this provider's "
            "category."
        )


def _render_template(template: str, placeholders: dict[str, str]) -> str:
    return template.format_map(_MissingPlaceholderDict(placeholders))


def _render_value(value: Any, placeholders: dict[str, str]) -> Any:
    if isinstance(value, str):
        return _render_template(value, placeholders)

    if isinstance(value, dict):
        return {key: _render_value(item, placeholders) for key, item in value.items()}

    if isinstance(value, list):
        return [_render_value(item, placeholders) for item in value]

    return value


def _get_by_path(obj: Any, path: str, *, required: bool) -> Any | None:
    """
    Walk a dot-path into a parsed JSON structure.

    Numeric segments are treated as list indices, everything else as a
    dict key. required=True raises HttpAdapterTemplateError naming the
    exact failing segment; required=False returns None instead, for
    optional result fields (title, thumbnail, and so on).
    """

    current = obj
    walked: list[str] = []

    for segment in path.split("."):
        walked.append(segment)

        try:
            if segment.lstrip("-").isdigit():
                current = current[int(segment)]
            else:
                current = current[segment]
        except (KeyError, IndexError, TypeError):
            if required:
                raise HttpAdapterTemplateError(
                    f"Response field path '{path}' could not be resolved "
                    f"at segment '{'.'.join(walked)}' - the response did "
                    "not have the expected shape."
                ) from None

            return None

    return current


class HttpProviderExecutor:
    """
    Shared HTTP execution for no-code (generic) provider adapters.

    Mirrors StockDownloadService's injectable `opener` pattern: a
    Transport callable stands in for the real `requests` call in
    tests, so no test in this codebase ever needs a live network
    connection to exercise a no-code provider.
    """

    def __init__(self, *, transport: Transport | None = None) -> None:
        self._transport = transport or default_transport

    def execute(
        self,
        config: HttpAdapterConfig,
        *,
        placeholders: dict[str, str],
        api_key: str,
        base_url: str | None = None,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> HttpTransportResponse:
        """Render config's templates and send the resulting request."""

        full_placeholders = {
            **placeholders,
            "api_key": api_key,
            "base_url": base_url or "",
        }

        url = _render_template(config.url_template, full_placeholders)

        headers = {
            key: _render_template(value, full_placeholders)
            for key, value in config.headers.items()
        }

        params = {
            key: _render_template(value, full_placeholders)
            for key, value in config.query_params.items()
        } or None

        json_body = (
            _render_value(config.json_body_template, full_placeholders)
            if config.json_body_template is not None
            else None
        )

        request = PreparedHttpRequest(
            method=config.http_method.value,
            url=url,
            headers=headers,
            params=params,
            json_body=json_body,
            timeout_seconds=timeout_seconds,
        )

        response = self._transport(request)

        if response.status_code >= 400:
            raise HttpProviderExecutionError(
                f"Provider returned HTTP {response.status_code} for "
                f"{request.method} {request.url}."
            )

        return response

    def extract_binary_file(
        self,
        response: HttpTransportResponse,
        *,
        destination_directory: str | Path,
        default_extension: str,
        config: HttpAdapterConfig,
    ) -> str:
        """Write a binary response body to a new file, return its path."""

        extension = config.response_binary_file_extension or default_extension
        directory = Path(destination_directory)
        directory.mkdir(parents=True, exist_ok=True)

        destination = directory / f"{uuid4()}{extension}"
        destination.write_bytes(response.content)

        return str(destination.resolve())

    def extract_json_file_url(
        self,
        response: HttpTransportResponse,
        config: HttpAdapterConfig,
    ) -> str:
        """Extract a downloadable file URL from a JSON response."""

        if not config.response_file_url_path:
            raise HttpAdapterTemplateError(
                "response_file_url_path is required to extract a file URL."
            )

        payload = self._parse_json(response)

        url = _get_by_path(payload, config.response_file_url_path, required=True)

        if not isinstance(url, str) or not url:
            raise HttpAdapterTemplateError(
                f"Response field path '{config.response_file_url_path}' did "
                "not resolve to a non-empty URL string."
            )

        return url

    def download_to_file(
        self,
        url: str,
        *,
        destination_directory: str | Path,
        default_extension: str,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> str:
        """Fetch a plain URL (the follow-up step for JSON_FILE_URL mode)."""

        response = self._transport(
            PreparedHttpRequest(
                method="GET",
                url=url,
                timeout_seconds=timeout_seconds,
            )
        )

        if response.status_code >= 400:
            raise HttpProviderExecutionError(
                f"Downloading the generated file failed with HTTP "
                f"{response.status_code}: {url}"
            )

        directory = Path(destination_directory)
        directory.mkdir(parents=True, exist_ok=True)

        destination = directory / f"{uuid4()}{default_extension}"
        destination.write_bytes(response.content)

        return str(destination.resolve())

    def extract_json_result_list(
        self,
        response: HttpTransportResponse,
        config: HttpAdapterConfig,
        *,
        provider_name: str,
        query: str,
    ) -> list[StockSearchResult]:
        """Map a JSON search response into normalized StockSearchResults."""

        if not config.response_list_path or config.response_field_mapping is None:
            raise HttpAdapterTemplateError(
                "response_list_path and response_field_mapping are required "
                "to extract a result list."
            )

        payload = self._parse_json(response)

        items = _get_by_path(payload, config.response_list_path, required=True)

        if not isinstance(items, list):
            raise HttpAdapterTemplateError(
                f"Response field path '{config.response_list_path}' did "
                "not resolve to a list of results."
            )

        mapping = config.response_field_mapping
        results: list[StockSearchResult] = []

        for index, item in enumerate(items):
            file_url = _get_by_path(item, mapping.file_url_path, required=True)

            if not isinstance(file_url, str) or not file_url:
                raise HttpAdapterTemplateError(
                    f"Response field path '{mapping.file_url_path}' did not "
                    f"resolve to a non-empty URL string for result {index}."
                )

            provider_asset_id = self._optional_text(
                (
                    _get_by_path(item, mapping.provider_asset_id_path, required=False)
                    if mapping.provider_asset_id_path
                    else None
                ),
                default=str(index),
            )

            title = self._optional_text(
                (
                    _get_by_path(item, mapping.title_path, required=False)
                    if mapping.title_path
                    else None
                ),
                default=query,
            )

            results.append(
                StockSearchResult(
                    provider=provider_name,
                    provider_asset_id=provider_asset_id,
                    title=title,
                    page_url=self._optional_path(item, mapping.page_url_path),
                    file_url=file_url,
                    thumbnail_url=self._optional_path(item, mapping.thumbnail_url_path),
                    duration_seconds=self._optional_number(
                        self._optional_path(item, mapping.duration_seconds_path),
                        default=0.0,
                    ),
                    width=self._optional_int(
                        self._optional_path(item, mapping.width_path)
                    ),
                    height=self._optional_int(
                        self._optional_path(item, mapping.height_path)
                    ),
                    file_type=mapping.file_type,
                )
            )

        return results

    @staticmethod
    def _parse_json(response: HttpTransportResponse) -> Any:
        try:
            return json.loads(response.content)
        except json.JSONDecodeError as error:
            raise HttpAdapterTemplateError(
                f"Response was not valid JSON: {error}"
            ) from error

    @staticmethod
    def _optional_path(item: Any, path: str | None) -> Any | None:
        if not path:
            return None

        return _get_by_path(item, path, required=False)

    @staticmethod
    def _optional_text(value: Any | None, *, default: str) -> str:
        if isinstance(value, str) and value:
            return value

        return default

    @staticmethod
    def _optional_number(value: Any | None, *, default: float) -> float:
        if isinstance(value, (int, float)):
            return float(value)

        return default

    @staticmethod
    def _optional_int(value: Any | None) -> int | None:
        if isinstance(value, (int, float)):
            return int(value)

        return None
