from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

import openai
from openai import OpenAI

from src.shared.llm.models import (
    LLMProvider,
    LLMUsage,
)
from src.shared.llm.providers import (
    LLMProviderAdapter,
    LLMProviderResponse,
)
from src.shared.llm.request import LLMRequest


class OpenAIResponsesClient(Protocol):
    """Minimal client contract required by the OpenAI adapter."""

    def create(
        self,
        **kwargs: Any,
    ) -> Any:
        """Create one OpenAI Responses API request."""
        ...


class OpenAIProviderAdapter(LLMProviderAdapter):
    """Production OpenAI adapter using the Responses API."""

    provider = LLMProvider.OPENAI

    def __init__(
        self,
        *,
        api_key: str,
        client: OpenAI | None = None,
    ) -> None:
        normalized_api_key = api_key.strip()

        if not normalized_api_key:
            raise ValueError(
                "OpenAI API key cannot be empty."
            )

        self._client = client or OpenAI(
            api_key=normalized_api_key,
        )

    def create_operation(
        self,
        request: LLMRequest,
    ) -> Callable[[], LLMProviderResponse]:
        """Create a retry-compatible OpenAI operation."""

        if request.provider != LLMProvider.OPENAI:
            raise ValueError(
                "OpenAIProviderAdapter requires an OpenAI request."
            )

        def operation() -> LLMProviderResponse:
            return self._execute(request)

        return operation

    def _execute(
        self,
        request: LLMRequest,
    ) -> LLMProviderResponse:
        """Execute one OpenAI Responses API request."""

        request_arguments: dict[str, Any] = {
            "model": request.model,
            "input": request.prompt,
        }

        if request.system_prompt is not None:
            request_arguments["instructions"] = (
                request.system_prompt
            )

        if request.max_output_tokens is not None:
            request_arguments["max_output_tokens"] = (
                request.max_output_tokens
            )

        if request.temperature != 0.7:
            request_arguments["temperature"] = (
                request.temperature
            )

        try:
            response = self._client.with_options(
                timeout=request.timeout_seconds,
            ).responses.create(
                **request_arguments,
            )

        except openai.APITimeoutError as error:
            raise TimeoutError(
                "OpenAI request timed out."
            ) from error

        except openai.APIConnectionError as error:
            raise ConnectionError(
                "Could not connect to OpenAI."
            ) from error

        except openai.RateLimitError as error:
            raise ConnectionError(
                "OpenAI rate limit reached."
            ) from error

        except openai.APIStatusError as error:
            error_request_id = (
                str(error.request_id)
                if error.request_id is not None
                else "unknown"
            )

            raise RuntimeError(
                "OpenAI API request failed with "
                f"status {error.status_code}; "
                f"request_id={error_request_id}."
            ) from error

        content = response.output_text or ""
        usage = self._extract_usage(response)

        raw_request_id = getattr(
            response,
            "_request_id",
            None,
        )

        provider_request_id: str | None = (
            str(raw_request_id)
            if raw_request_id is not None
            else None
        )

        raw_response_id = getattr(
            response,
            "id",
            None,
        )

        response_id = (
            str(raw_response_id)
            if raw_response_id is not None
            else ""
        )

        return LLMProviderResponse(
            content=content,
            usage=usage,
            provider_request_id=provider_request_id,
            metadata={
                "response_id": response_id,
                "provider": "openai",
            },
        )

    @staticmethod
    def _extract_usage(
        response: Any,
    ) -> LLMUsage:
        """Convert OpenAI usage into normalized usage."""

        raw_usage = getattr(
            response,
            "usage",
            None,
        )

        if raw_usage is None:
            return LLMUsage()

        input_tokens = int(
            getattr(
                raw_usage,
                "input_tokens",
                0,
            )
            or 0
        )

        output_tokens = int(
            getattr(
                raw_usage,
                "output_tokens",
                0,
            )
            or 0
        )

        total_tokens = int(
            getattr(
                raw_usage,
                "total_tokens",
                input_tokens + output_tokens,
            )
            or 0
        )

        return LLMUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=0.0,
        )