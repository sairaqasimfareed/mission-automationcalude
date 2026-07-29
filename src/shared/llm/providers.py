from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from pydantic import Field

from src.models.base import MissionBaseModel
from src.shared.llm.models import (
    LLMProvider,
    LLMUsage,
)
from src.shared.llm.request import LLMRequest


class LLMProviderResponse(MissionBaseModel):
    """Normalized raw response returned by one LLM adapter."""

    content: str

    usage: LLMUsage = Field(
        default_factory=LLMUsage,
    )

    provider_request_id: str | None = None

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )


class LLMProviderAdapter(ABC):
    """Base interface for every LLM provider adapter."""

    provider: LLMProvider

    @abstractmethod
    def create_operation(
        self,
        request: LLMRequest,
    ) -> Callable[[], LLMProviderResponse]:
        """Create one provider operation."""

        raise NotImplementedError


class AnthropicProviderAdapter(LLMProviderAdapter):
    """Anthropic adapter skeleton."""

    provider = LLMProvider.ANTHROPIC

    def create_operation(
        self,
        request: LLMRequest,
    ) -> Callable[[], LLMProviderResponse]:
        def operation() -> LLMProviderResponse:
            raise NotImplementedError(
                "Anthropic API integration is not configured."
            )

        return operation


class GeminiProviderAdapter(LLMProviderAdapter):
    """Gemini adapter skeleton."""

    provider = LLMProvider.GEMINI

    def create_operation(
        self,
        request: LLMRequest,
    ) -> Callable[[], LLMProviderResponse]:
        def operation() -> LLMProviderResponse:
            raise NotImplementedError(
                "Gemini API integration is not configured."
            )

        return operation