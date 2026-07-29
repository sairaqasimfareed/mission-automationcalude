from src.shared.llm.models import LLMProvider
from src.shared.llm.openai_provider import (
    OpenAIProviderAdapter,
)
from src.shared.llm.providers import (
    AnthropicProviderAdapter,
    GeminiProviderAdapter,
    LLMProviderResponse,
)
from src.shared.llm.request import LLMRequest


openai_request = LLMRequest(
    provider=LLMProvider.OPENAI,
    model="test-model",
    prompt="Generate text.",
    prompt_version="v1",
)

anthropic_request = LLMRequest(
    provider=LLMProvider.ANTHROPIC,
    model="anthropic-test-model",
    prompt="Generate text.",
    prompt_version="v1",
)

gemini_request = LLMRequest(
    provider=LLMProvider.GEMINI,
    model="gemini-test-model",
    prompt="Generate text.",
    prompt_version="v1",
)


openai_adapter = OpenAIProviderAdapter(
    api_key="test-api-key",
)

anthropic_adapter = AnthropicProviderAdapter()
gemini_adapter = GeminiProviderAdapter()


assert openai_adapter.provider == LLMProvider.OPENAI
assert anthropic_adapter.provider == LLMProvider.ANTHROPIC
assert gemini_adapter.provider == LLMProvider.GEMINI


for adapter, request in (
    (
        anthropic_adapter,
        anthropic_request,
    ),
    (
        gemini_adapter,
        gemini_request,
    ),
):
    operation = adapter.create_operation(request)

    assert callable(operation)

    try:
        operation()
    except NotImplementedError:
        print(
            f"{adapter.provider.value} skeleton correctly blocked."
        )
    else:
        raise AssertionError(
            "Skeleton provider should not perform a real call."
        )


openai_operation = openai_adapter.create_operation(
    openai_request
)

assert callable(openai_operation)


response = LLMProviderResponse(
    content="Normalized response",
)

assert response.content == "Normalized response"
assert response.usage.total_tokens == 0
assert response.provider_request_id is None


print("LLM Providers tests completed successfully.")