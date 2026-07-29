from src.shared.llm.models import LLMProvider
from src.shared.llm.providers import (
    AnthropicProviderAdapter,
    OpenAIProviderAdapter,
)


openai_adapter = OpenAIProviderAdapter()
anthropic_adapter = AnthropicProviderAdapter()

print("OpenAI provider:", openai_adapter.provider)
print("Anthropic provider:", anthropic_adapter.provider)

assert openai_adapter.provider == LLMProvider.OPENAI
assert anthropic_adapter.provider == LLMProvider.ANTHROPIC


openai_operation = openai_adapter.create_operation(
    model="test-openai-model",
    prompt="Write a test response.",
)

anthropic_operation = anthropic_adapter.create_operation(
    model="test-anthropic-model",
    prompt="Review this test script.",
)

assert callable(openai_operation)
assert callable(anthropic_operation)

try:
    openai_operation()
except NotImplementedError as error:
    print("OpenAI skeleton correctly blocked:", error)
else:
    raise AssertionError("OpenAI skeleton should not make a real API call.")


try:
    anthropic_operation()
except NotImplementedError as error:
    print("Anthropic skeleton correctly blocked:", error)
else:
    raise AssertionError("Anthropic skeleton should not make a real API call.")


print("LLM provider adapter tests completed successfully.")