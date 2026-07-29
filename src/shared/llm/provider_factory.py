from __future__ import annotations

from src.config.settings import settings
from src.shared.llm.dry_run_provider import (
    DryRunProviderAdapter,
)
from src.shared.llm.models import LLMProvider
from src.shared.llm.openai_provider import (
    OpenAIProviderAdapter,
)
from src.shared.llm.providers import (
    AnthropicProviderAdapter,
    GeminiProviderAdapter,
    LLMProviderAdapter,
)


def create_provider_adapter(
    provider: LLMProvider,
    *,
    api_key: str | None = None,
) -> LLMProviderAdapter:
    """Create the requested LLM adapter."""

    if settings.MISSION_AUTOMATION_DRY_RUN:
        return DryRunProviderAdapter()

    if provider == LLMProvider.OPENAI:
        if api_key is None or not api_key.strip():
            raise ValueError(
                "OpenAI provider requires an API key."
            )

        return OpenAIProviderAdapter(
            api_key=api_key,
        )

    if provider == LLMProvider.ANTHROPIC:
        return AnthropicProviderAdapter()

    if provider == LLMProvider.GEMINI:
        return GeminiProviderAdapter()

    raise ValueError(
        f"Unsupported LLM provider: {provider}"
    )