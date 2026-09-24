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
    dry_run: bool | None = None,
) -> LLMProviderAdapter:
    """
    Create the requested production or dry-run LLM adapter.

    dry_run defaults to None, which reads the global settings singleton
    (this function's own long-standing, tested behavior for a simple,
    direct caller - see tests/test_llm_provider_factory.py). Real bug
    found and fixed 2026-09-24: that global is loaded once from the
    real .env file at import time, so it can silently disagree with
    whatever Settings a specific runtime was actually explicitly
    configured with (a test building its own dry-run Settings object,
    for instance) - ProviderFactory.create_llm_adapter() now always
    passes its own, correct, per-runtime dry_run value explicitly
    instead of relying on this fallback, which is why a caller that
    matters (the real production/test call path) must never omit it.
    """

    effective_dry_run = (
        dry_run if dry_run is not None else settings.MISSION_AUTOMATION_DRY_RUN
    )

    if effective_dry_run:
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
