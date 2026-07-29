from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

from src.shared.llm.models import LLMProvider


class LLMProviderAdapter(ABC):
    """Base interface for every LLM provider adapter."""

    provider: LLMProvider

    @abstractmethod
    def create_operation(
        self,
        *,
        model: str,
        prompt: str,
        system_prompt: str | None = None,
    ) -> Callable[[], str]:
        """
        Return a callable that performs the provider API request.

        The returned callable will later be executed by LLMGateway,
        so retry, circuit-breaker, logging, and JSON handling remain centralized.
        """
        raise NotImplementedError


class OpenAIProviderAdapter(LLMProviderAdapter):
    """OpenAI adapter skeleton. Real API integration will be added later."""

    provider = LLMProvider.OPENAI

    def create_operation(
        self,
        *,
        model: str,
        prompt: str,
        system_prompt: str | None = None,
    ) -> Callable[[], str]:
        def operation() -> str:
            raise NotImplementedError(
                "OpenAI API integration has not been configured yet."
            )

        return operation


class AnthropicProviderAdapter(LLMProviderAdapter):
    """Anthropic adapter skeleton. Real API integration will be added later."""

    provider = LLMProvider.ANTHROPIC

    def create_operation(
        self,
        *,
        model: str,
        prompt: str,
        system_prompt: str | None = None,
    ) -> Callable[[], str]:
        def operation() -> str:
            raise NotImplementedError(
                "Anthropic API integration has not been configured yet."
            )

        return operation