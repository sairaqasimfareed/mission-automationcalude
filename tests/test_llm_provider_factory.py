from src.config.settings import settings
from src.shared.llm.models import LLMProvider
from src.shared.llm.provider_factory import (
    create_provider_adapter,
)
from src.shared.llm.dry_run_provider import (
    DryRunProviderAdapter,
)
from src.shared.llm.openai_provider import (
    OpenAIProviderAdapter,
)
from src.shared.llm.gemini_provider import (
    GeminiProviderAdapter,
)
from src.shared.llm.providers import (
    AnthropicProviderAdapter,
)


original = settings.MISSION_AUTOMATION_DRY_RUN


#
# Dry Run
#
settings.MISSION_AUTOMATION_DRY_RUN = True

adapter = create_provider_adapter(
    LLMProvider.OPENAI,
)

assert isinstance(
    adapter,
    DryRunProviderAdapter,
)

print("Dry-run provider selected successfully.")


#
# Production OpenAI
#
settings.MISSION_AUTOMATION_DRY_RUN = False

adapter = create_provider_adapter(
    LLMProvider.OPENAI,
    api_key="test-key",
)

assert isinstance(
    adapter,
    OpenAIProviderAdapter,
)

print("OpenAI provider selected successfully.")


#
# Production Gemini
#
adapter = create_provider_adapter(
    LLMProvider.GEMINI,
    api_key="test-key",
)

assert isinstance(
    adapter,
    GeminiProviderAdapter,
)

print("Gemini provider selected successfully.")


#
# Anthropic
#
adapter = create_provider_adapter(
    LLMProvider.ANTHROPIC,
)

assert isinstance(
    adapter,
    AnthropicProviderAdapter,
)

print("Anthropic provider selected successfully.")


#
# Missing OpenAI key
#
try:
    create_provider_adapter(
        LLMProvider.OPENAI,
    )
except ValueError:
    print("Missing OpenAI key blocked.")
else:
    raise AssertionError()


#
# Missing Gemini key
#
try:
    create_provider_adapter(
        LLMProvider.GEMINI,
    )
except ValueError:
    print("Missing Gemini key blocked.")
else:
    raise AssertionError()


settings.MISSION_AUTOMATION_DRY_RUN = original

print(
    "LLM Provider Factory tests completed successfully."
)