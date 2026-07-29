from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field

from src.models.base import MissionBaseModel


class LLMProvider(str, Enum):
    """Supported LLM providers."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"


class LLMCallStatus(str, Enum):
    """Possible outcomes of an LLM call."""

    SUCCESS = "success"
    RETRY_EXHAUSTED = "retry_exhausted"
    MALFORMED_RESPONSE = "malformed_response"
    CIRCUIT_OPEN = "circuit_open"
    BLOCKED_BY_BUDGET = "blocked_by_budget"
    PROVIDER_ERROR = "provider_error"


class LLMUsage(MissionBaseModel):
    """Normalized token and cost usage for one LLM call."""

    input_tokens: int = Field(
        default=0,
        ge=0,
    )

    output_tokens: int = Field(
        default=0,
        ge=0,
    )

    total_tokens: int = Field(
        default=0,
        ge=0,
    )

    estimated_cost_usd: float = Field(
        default=0.0,
        ge=0.0,
    )


class LLMCallResult(MissionBaseModel):
    """Standard result returned by every LLM provider call."""

    status: LLMCallStatus
    provider: LLMProvider
    model: str

    content: str | None = None
    parsed_data: dict[str, Any] | None = None

    latency_seconds: float = Field(
        default=0.0,
        ge=0.0,
    )

    retry_count: int = Field(
        default=0,
        ge=0,
    )

    usage: LLMUsage = Field(
        default_factory=LLMUsage,
    )

    provider_request_id: str | None = None

    error_message: str | None = None

    warnings: list[str] = Field(
        default_factory=list,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @property
    def is_success(self) -> bool:
        """Return whether the LLM call completed successfully."""

        return self.status == LLMCallStatus.SUCCESS