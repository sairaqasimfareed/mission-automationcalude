from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from src.shared.llm.circuit_breaker import CircuitBreaker
from src.shared.llm.models import (
    LLMCallResult,
    LLMCallStatus,
    LLMProvider,
)
from src.shared.llm.providers import LLMProviderResponse
from src.shared.llm.retry import (
    RetryConfig,
    RetryExhaustedError,
    execute_with_retry,
)
from src.shared.logger import logger


class LLMGateway:
    """Shared gateway for all LLM provider calls."""

    def __init__(
        self,
        retry_config: RetryConfig | None = None,
        circuit_breakers: dict[LLMProvider, CircuitBreaker] | None = None,
    ) -> None:
        self.retry_config = retry_config or RetryConfig()

        self.circuit_breakers = circuit_breakers or {
            LLMProvider.OPENAI: CircuitBreaker(),
            LLMProvider.ANTHROPIC: CircuitBreaker(),
            LLMProvider.GEMINI: CircuitBreaker(),
        }

    @staticmethod
    def _log_result(result: LLMCallResult) -> None:
        """Write one structured log entry for an LLM call."""

        logger.info(
            "llm_call | provider=%s | model=%s | status=%s | "
            "latency_seconds=%.4f | retry_count=%s | "
            "input_tokens=%s | output_tokens=%s | "
            "estimated_cost_usd=%.6f | error=%s",
            result.provider.value,
            result.model,
            result.status.value,
            result.latency_seconds,
            result.retry_count,
            result.usage.input_tokens,
            result.usage.output_tokens,
            result.usage.estimated_cost_usd,
            result.error_message,
        )

    def call(
        self,
        *,
        provider: LLMProvider,
        model: str,
        operation: Callable[[], LLMProviderResponse],
        expect_json: bool = False,
        retryable_exceptions: tuple[type[Exception], ...] = (
            TimeoutError,
            ConnectionError,
        ),
    ) -> LLMCallResult:
        """Execute an LLM call with retry and circuit-breaker protection."""

        breaker = self.circuit_breakers[provider]

        if not breaker.can_execute():
            result = LLMCallResult(
                status=LLMCallStatus.CIRCUIT_OPEN,
                provider=provider,
                model=model,
                error_message=(
                    f"{provider.value} circuit breaker is open."
                ),
            )
            self._log_result(result)
            return result

        started_at = time.perf_counter()

        try:
            provider_response, retry_count = execute_with_retry(
                operation=operation,
                config=self.retry_config,
                retryable_exceptions=retryable_exceptions,
            )

        except RetryExhaustedError as error:
            breaker.record_failure()

            result = LLMCallResult(
                status=LLMCallStatus.RETRY_EXHAUSTED,
                provider=provider,
                model=model,
                latency_seconds=time.perf_counter() - started_at,
                retry_count=max(
                    self.retry_config.max_attempts - 1,
                    0,
                ),
                error_message=str(error),
            )
            self._log_result(result)
            return result

        content = provider_response.content
        parsed_data: dict[str, Any] | None = None

        if expect_json:
            try:
                parsed_value = json.loads(content)

            except (json.JSONDecodeError, TypeError) as error:
                breaker.record_failure()

                result = LLMCallResult(
                    status=LLMCallStatus.MALFORMED_RESPONSE,
                    provider=provider,
                    model=model,
                    content=content,
                    latency_seconds=time.perf_counter() - started_at,
                    retry_count=retry_count,
                    usage=provider_response.usage,
                    provider_request_id=(
                        provider_response.provider_request_id
                    ),
                    metadata=provider_response.metadata,
                    error_message=(
                        f"Malformed JSON response: {error}"
                    ),
                )
                self._log_result(result)
                return result

            if not isinstance(parsed_value, dict):
                breaker.record_failure()

                result = LLMCallResult(
                    status=LLMCallStatus.MALFORMED_RESPONSE,
                    provider=provider,
                    model=model,
                    content=content,
                    latency_seconds=time.perf_counter() - started_at,
                    retry_count=retry_count,
                    usage=provider_response.usage,
                    provider_request_id=(
                        provider_response.provider_request_id
                    ),
                    metadata=provider_response.metadata,
                    error_message=(
                        "Expected a JSON object but received "
                        "another JSON type."
                    ),
                )
                self._log_result(result)
                return result

            parsed_data = parsed_value

        breaker.record_success()

        result = LLMCallResult(
            status=LLMCallStatus.SUCCESS,
            provider=provider,
            model=model,
            content=content,
            parsed_data=parsed_data,
            latency_seconds=time.perf_counter() - started_at,
            retry_count=retry_count,
            usage=provider_response.usage,
            provider_request_id=(
                provider_response.provider_request_id
            ),
            metadata=provider_response.metadata,
        )

        self._log_result(result)

        return result