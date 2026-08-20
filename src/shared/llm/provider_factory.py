from __future__ import annotations

from src.config.settings import settings
from src.shared.llm.anthropic_provider import (
    AnthropicProviderAdapter,
)
from src.shared.llm.dry_run_provider import (
    DryRunProviderAdapter,
)
from src.shared.llm.gemini_provider import (
    GeminiProviderAdapter,
)
from src.shared.llm.models import LLMProvider
from src.shared.llm.openai_provider import (
    OpenAIProviderAdapter,
)
from src.shared.llm.providers import (
    LLMProviderAdapter,
)


def create_provider_adapter(
    provider: LLMProvider,
    *,
    api_key: str | None = None,
) -> LLMProviderAdapter:
    """Create the requested production or dry-run LLM adapter."""

    if settings.MISSION_AUTOMATION_DRY_RUN:
        return DryRunProviderAdapter()

    normalized_api_key = api_key.strip() if api_key is not None else ""

    if not normalized_api_key:
        raise ValueError(f"{provider.value} provider requires an API key.")

    if provider == LLMProvider.OPENAI:
        return OpenAIProviderAdapter(
            api_key=normalized_api_key,
        )

    if provider == LLMProvider.GEMINI:
        return GeminiProviderAdapter(
            api_key=normalized_api_key,
        )

    if provider == LLMProvider.ANTHROPIC:
        return AnthropicProviderAdapter(
            api_key=normalized_api_key,
        )

    raise ValueError(f"Unsupported LLM provider: {provider}")
