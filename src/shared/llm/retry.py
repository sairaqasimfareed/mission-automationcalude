from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RetryConfig:
    """Configuration for retry behavior."""

    max_attempts: int = 3
    initial_delay_seconds: float = 1.0
    backoff_multiplier: float = 2.0
    max_delay_seconds: float = 10.0


class RetryExhaustedError(Exception):
    """Raised when all retry attempts have failed."""


def execute_with_retry(
    operation: Callable[[], Any],
    config: RetryConfig | None = None,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
) -> tuple[Any, int]:
    """
    Execute an operation with exponential backoff.

    Returns:
        A tuple containing:
        - operation result
        - number of retries performed

    Raises:
        RetryExhaustedError:
            When all configured attempts fail.
    """

    retry_config = config or RetryConfig()

    if retry_config.max_attempts < 1:
        raise ValueError("max_attempts must be at least 1.")

    delay = retry_config.initial_delay_seconds
    last_error: Exception | None = None

    for attempt in range(1, retry_config.max_attempts + 1):
        try:
            result = operation()
            retry_count = attempt - 1
            return result, retry_count

        except retryable_exceptions as error:
            last_error = error

            if attempt >= retry_config.max_attempts:
                break

            time.sleep(delay)

            delay = min(
                delay * retry_config.backoff_multiplier,
                retry_config.max_delay_seconds,
            )

    raise RetryExhaustedError(
        f"Operation failed after {retry_config.max_attempts} attempts."
    ) from last_error
