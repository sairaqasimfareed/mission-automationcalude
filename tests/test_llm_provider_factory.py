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
from src.shared.llm.provider_factory import (
    create_provider_adapter,
)


original_dry_run_setting = (
    settings.MISSION_AUTOMATION_DRY_RUN
)


settings.MISSION_AUTOMATION_DRY_RUN = True

dry_run_adapter = create_provider_adapter(
    LLMProvider.OPENAI,
)

assert isinstance(
    dry_run_adapter,
    DryRunProviderAdapter,
)

print("Dry-run provider selected successfully.")


settings.MISSION_AUTOMATION_DRY_RUN = False

openai_adapter = create_provider_adapter(
    LLMProvider.OPENAI,
    api_key="openai-test-key",
)

assert isinstance(
    openai_adapter,
    OpenAIProviderAdapter,
)

print("OpenAI provider selected successfully.")


gemini_adapter = create_provider_adapter(
    LLMProvider.GEMINI,
    api_key="gemini-test-key",
)

assert isinstance(
    gemini_adapter,
    GeminiProviderAdapter,
)

print("Gemini provider selected successfully.")


anthropic_adapter = create_provider_adapter(
    LLMProvider.ANTHROPIC,
    api_key="anthropic-test-key",
)

assert isinstance(
    anthropic_adapter,
    AnthropicProviderAdapter,
)

print("Anthropic provider selected successfully.")


for provider in (
    LLMProvider.OPENAI,
    LLMProvider.GEMINI,
    LLMProvider.ANTHROPIC,
):
    try:
        create_provider_adapter(
            provider,
        )
    except ValueError:
        print(
            f"Missing {provider.value} API key blocked."
        )
    else:
        raise AssertionError(
            f"{provider.value} should require an API key."
        )


settings.MISSION_AUTOMATION_DRY_RUN = (
    original_dry_run_setting
)

print(
    "LLM Provider Factory tests completed successfully."
)