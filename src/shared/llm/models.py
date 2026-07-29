from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class LLMProvider(str, Enum):
    """Supported LLM providers."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"


class LLMCallStatus(str, Enum):
    """Possible outcomes of an LLM call."""

    SUCCESS = "success"
    RETRY_EXHAUSTED = "retry_exhausted"
    MALFORMED_RESPONSE = "malformed_response"
    CIRCUIT_OPEN = "circuit_open"
    BLOCKED_BY_BUDGET = "blocked_by_budget"


class LLMCallResult(BaseModel):
    """Standard result returned by every LLM provider call."""

    status: LLMCallStatus
    provider: LLMProvider
    model: str

    content: str | None = None
    parsed_data: dict[str, Any] | None = None

    latency_seconds: float = 0.0
    retry_count: int = 0

    error_message: str | None = None
    warnings: list[str] = Field(default_factory=list)

    @property
    def is_success(self) -> bool:
        """Return True only when the LLM call succeeded."""

        return self.status == LLMCallStatus.SUCCESS