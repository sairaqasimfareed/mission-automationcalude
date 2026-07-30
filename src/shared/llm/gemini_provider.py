from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from google import genai
from google.genai import Client, types

from src.shared.llm.models import (
    LLMProvider,
    LLMUsage,
)
from src.shared.llm.providers import (
    LLMProviderAdapter,
    LLMProviderResponse,
)
from src.shared.llm.request import LLMRequest


class GeminiModelsClient(Protocol):
    """Minimal Gemini models-client contract."""

    def generate_content(
        self,
        **kwargs: Any,
    ) -> Any:
        """Generate one Gemini response."""
        ...


class GeminiProviderAdapter(LLMProviderAdapter):
    """Production Gemini adapter using Google Gen AI SDK."""

    provider = LLMProvider.GEMINI

    def __init__(
        self,
        *,
        api_key: str,
        client: Client | None = None,
    ) -> None:
        normalized_api_key = api_key.strip()

        if not normalized_api_key:
            raise ValueError(
                "Gemini API key cannot be empty."
            )

        self._client = client or genai.Client(
            api_key=normalized_api_key,
        )

    def create_operation(
        self,
        request: LLMRequest,
    ) -> Callable[[], LLMProviderResponse]:
        """Create a retry-compatible Gemini operation."""

        if request.provider != LLMProvider.GEMINI:
            raise ValueError(
                "GeminiProviderAdapter requires a Gemini request."
            )

        def operation() -> LLMProviderResponse:
            return self._execute(request)

        return operation

    def _execute(
        self,
        request: LLMRequest,
    ) -> LLMProviderResponse:
        """Execute one Gemini generate-content request."""

        generation_config = self._build_config(request)

        response = self._client.models.generate_content(
            model=request.model,
            contents=request.prompt,
            config=generation_config,
        )

        content = response.text or ""
        usage = self._extract_usage(response)

        raw_response_id = getattr(
            response,
            "response_id",
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
            provider_request_id=(
                response_id or None
            ),
            metadata={
                "provider": "gemini",
                "response_id": response_id,
                "json_mode": request.expect_json,
            },
        )

    @staticmethod
    def _build_config(
        request: LLMRequest,
    ) -> types.GenerateContentConfig:
        """Build Gemini generation configuration."""

        config_arguments: dict[str, Any] = {
            "temperature": request.temperature,
        }

        if request.system_prompt is not None:
            config_arguments["system_instruction"] = (
                request.system_prompt
            )

        if request.max_output_tokens is not None:
            config_arguments["max_output_tokens"] = (
                request.max_output_tokens
            )

        if request.expect_json:
            config_arguments["response_mime_type"] = (
                "application/json"
            )

            if request.response_schema is not None:
                config_arguments["response_schema"] = (
                    request.response_schema
                )

        return types.GenerateContentConfig(
            **config_arguments,
        )

    @staticmethod
    def _extract_usage(
        response: Any,
    ) -> LLMUsage:
        """Convert Gemini usage metadata into normalized usage."""

        raw_usage = getattr(
            response,
            "usage_metadata",
            None,
        )

        if raw_usage is None:
            return LLMUsage()

        input_tokens = int(
            getattr(
                raw_usage,
                "prompt_token_count",
                0,
            )
            or 0
        )

        output_tokens = int(
            getattr(
                raw_usage,
                "candidates_token_count",
                0,
            )
            or 0
        )

        total_tokens = int(
            getattr(
                raw_usage,
                "total_token_count",
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