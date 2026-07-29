from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    """Simple in-memory circuit breaker for an LLM provider."""

    failure_threshold: int = 3
    recovery_timeout_seconds: int = 60

    failure_count: int = 0
    state: CircuitState = CircuitState.CLOSED
    opened_at: datetime | None = None

    def can_execute(self) -> bool:
        """Return whether a provider call may proceed."""

        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            if self.opened_at is None:
                return False

            recovery_time = self.opened_at + timedelta(
                seconds=self.recovery_timeout_seconds
            )

            if datetime.now(UTC) >= recovery_time:
                self.state = CircuitState.HALF_OPEN
                return True

            return False

        return True

    def record_success(self) -> None:
        """Reset the breaker after a successful call."""

        self.failure_count = 0
        self.state = CircuitState.CLOSED
        self.opened_at = None

    def record_failure(self) -> None:
        """Open the breaker when the failure threshold is reached."""

        self.failure_count += 1

        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            self.opened_at = datetime.now(UTC)
