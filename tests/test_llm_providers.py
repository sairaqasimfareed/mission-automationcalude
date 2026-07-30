from src.shared.llm.anthropic_provider import (
    AnthropicProviderAdapter,
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
    LLMProviderResponse,
)


assert issubclass(
    OpenAIProviderAdapter,
    LLMProviderAdapter,
)

assert issubclass(
    GeminiProviderAdapter,
    LLMProviderAdapter,
)

assert issubclass(
    AnthropicProviderAdapter,
    LLMProviderAdapter,
)

assert (
    OpenAIProviderAdapter.provider
    == LLMProvider.OPENAI
)

assert (
    GeminiProviderAdapter.provider
    == LLMProvider.GEMINI
)

assert (
    AnthropicProviderAdapter.provider
    == LLMProvider.ANTHROPIC
)


response = LLMProviderResponse(
    content="Normalized response",
)

assert response.content == "Normalized response"
assert response.usage.total_tokens == 0
assert response.provider_request_id is None
assert response.metadata == {}


print(
    "LLM Providers tests completed successfully."
)