from __future__ import annotations

from collections.abc import Callable
from typing import Any

import anthropic
from anthropic import Anthropic

from src.shared.llm.models import (
    LLMProvider,
    LLMUsage,
)
from src.shared.llm.providers import (
    LLMProviderAdapter,
    LLMProviderResponse,
)
from src.shared.llm.request import LLMRequest

# 2026-09-11 real fix, found live during this session's first real
# end-to-end content-generation call: unlike OpenAI/Gemini (where
# max_output_tokens is only sent when a caller explicitly sets it,
# letting the provider's own generous default apply), Anthropic's
# real Messages API requires max_tokens on every request - some
# fallback is unavoidable when a caller (e.g. ResearchAgent, which
# never sets max_output_tokens) omits one. The previous fallback,
# 1024, was too small for real content generation: a real research
# call against the live API consumed the entire 1024-token budget
# and returned a real response with zero "text" content blocks,
# surfacing as "Research provider returned empty content." - not a
# parsing bug, a genuinely too-small budget.
#
# Raised again the same day, still live-discovered: 8192 was not
# reliably enough either. Real Claude 5 responses include a real
# "thinking" content block that shares the same max_tokens budget
# with the actual "text" block - confirmed directly: one real call to
# the exact same prompt used only 1179 thinking tokens and finished
# normally (stop_reason="end_turn") with a full real text response,
# while another real call to the same prompt hit max_tokens=8192
# exactly with zero text ever produced, meaning that attempt spent
# the *entire* budget thinking. This is real, observed variance in
# how much a given call thinks, not a bug in a specific request - a
# fixed token budget needs real headroom for an occasional
# thinking-heavy attempt to still leave room for the actual answer.
_DEFAULT_MAX_OUTPUT_TOKENS = 16384


class AnthropicProviderAdapter(LLMProviderAdapter):
    """Production Anthropic adapter using the Claude Messages API."""

    provider = LLMProvider.ANTHROPIC

    def __init__(
        self,
        *,
        api_key: str,
        client: Anthropic | None = None,
    ) -> None:
        normalized_api_key = api_key.strip()

        if not normalized_api_key:
            raise ValueError("Anthropic API key cannot be empty.")

        self._client = client or Anthropic(
            api_key=normalized_api_key,
        )

    def create_operation(
        self,
        request: LLMRequest,
    ) -> Callable[[], LLMProviderResponse]:
        """Create a retry-compatible Anthropic operation."""

        if request.provider != LLMProvider.ANTHROPIC:
            raise ValueError(
                "AnthropicProviderAdapter requires " "an Anthropic request."
            )

        def operation() -> LLMProviderResponse:
            return self._execute(request)

        return operation

    def _execute(
        self,
        request: LLMRequest,
    ) -> LLMProviderResponse:
        """
        Execute one Claude Messages API request.

        2026-09-11 real fix, found live during this session's first
        real (non-dry-run) end-to-end test: the real Claude Messages
        API rejects an explicit temperature parameter for the current
        Claude 5 model family with a real HTTP 400 - the API's own
        error message: "temperature is deprecated for this model" -
        confirmed directly against the real API, not assumed.
        request.temperature is never sent to Anthropic; every other
        provider's request-building is unaffected. If a future caller
        genuinely needs Anthropic temperature control against an
        older model that still accepts it, this should become
        conditional (e.g. retry once without temperature only on this
        specific error) rather than removed outright as it is here.
        """

        request_arguments: dict[str, Any] = {
            "model": request.model,
            "max_tokens": (
                request.max_output_tokens
                if request.max_output_tokens is not None
                else _DEFAULT_MAX_OUTPUT_TOKENS
            ),
            "messages": [
                {
                    "role": "user",
                    "content": request.prompt,
                }
            ],
        }

        if request.system_prompt is not None:
            request_arguments["system"] = request.system_prompt

        try:
            response = self._client.with_options(
                timeout=request.timeout_seconds,
            ).messages.create(
                **request_arguments,
            )

        except anthropic.APITimeoutError as error:
            raise TimeoutError("Anthropic request timed out.") from error

        except anthropic.APIConnectionError as error:
            raise ConnectionError("Could not connect to Anthropic.") from error

        except anthropic.RateLimitError as error:
            raise ConnectionError("Anthropic rate limit was reached.") from error

        except anthropic.APIStatusError as error:
            raw_request_id = getattr(
                error,
                "request_id",
                None,
            )

            error_request_id = (
                str(raw_request_id) if raw_request_id is not None else "unknown"
            )

            raise RuntimeError(
                "Anthropic API request failed with "
                f"status {error.status_code}; "
                f"request_id={error_request_id}."
            ) from error

        content = self._extract_text(response)
        usage = self._extract_usage(response)

        raw_message_id = getattr(
            response,
            "id",
            None,
        )

        message_id = str(raw_message_id) if raw_message_id is not None else ""

        return LLMProviderResponse(
            content=content,
            usage=usage,
            provider_request_id=message_id or None,
            metadata={
                "provider": "anthropic",
                "message_id": message_id,
                "json_mode": request.expect_json,
                "stop_reason": str(
                    getattr(
                        response,
                        "stop_reason",
                        "",
                    )
                    or ""
                ),
            },
        )

    @staticmethod
    def _extract_text(
        response: Any,
    ) -> str:
        """Combine all text blocks from an Anthropic response."""

        content_blocks = getattr(
            response,
            "content",
            None,
        )

        if not content_blocks:
            return ""

        text_parts: list[str] = []

        for block in content_blocks:
            block_type = getattr(
                block,
                "type",
                None,
            )

            block_text = getattr(
                block,
                "text",
                None,
            )

            if block_type == "text" and isinstance(block_text, str):
                text_parts.append(block_text)

        return "".join(text_parts)

    @staticmethod
    def _extract_usage(
        response: Any,
    ) -> LLMUsage:
        """Convert Anthropic usage into normalized usage."""

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

        return LLMUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=(input_tokens + output_tokens),
            estimated_cost_usd=0.0,
        )
