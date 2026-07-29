from __future__ import annotations

from src.config.settings import settings
from src.shared.llm.dry_run_provider import DryRunProviderAdapter
from src.shared.llm.models import LLMProvider
from src.shared.llm.providers import (
    AnthropicProviderAdapter,
    LLMProviderAdapter,
    OpenAIProviderAdapter,
)


def create_provider_adapter(
    provider: LLMProvider,
) -> LLMProviderAdapter:
    """Create the correct provider adapter for the current environment."""

    if settings.MISSION_AUTOMATION_DRY_RUN:
        return DryRunProviderAdapter()

    if provider == LLMProvider.OPENAI:
        return OpenAIProviderAdapter()

    if provider == LLMProvider.ANTHROPIC:
        return AnthropicProviderAdapter()

    raise ValueError(f"Unsupported LLM provider: {provider}")