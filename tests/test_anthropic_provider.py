from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from src.shared.llm.anthropic_provider import (
    AnthropicProviderAdapter,
)
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest


class FakeAnthropicMessages:
    """Fake Messages API client for unit testing."""

    def __init__(self) -> None:
        self.last_arguments: dict[str, Any] = {}

    def create(
        self,
        **kwargs: Any,
    ) -> Any:
        self.last_arguments = kwargs

        assert kwargs["model"] == "claude-test-model"
        assert kwargs["max_tokens"] == 500
        assert kwargs["temperature"] == 0.4
        assert kwargs["system"] == ("You are a helpful assistant.")

        assert kwargs["messages"] == [
            {
                "role": "user",
                "content": "Generate a response.",
            }
        ]

        return SimpleNamespace(
            id="message-001",
            content=[
                SimpleNamespace(
                    type="text",
                    text="Claude normalized response",
                )
            ],
            usage=SimpleNamespace(
                input_tokens=30,
                output_tokens=20,
            ),
            stop_reason="end_turn",
        )


class FakeAnthropicClient:
    """Fake Anthropic client."""

    def __init__(self) -> None:
        self.messages = FakeAnthropicMessages()
        self.timeout: int | None = None

    def with_options(
        self,
        *,
        timeout: int,
    ) -> FakeAnthropicClient:
        self.timeout = timeout
        return self


fake_client = FakeAnthropicClient()

adapter = AnthropicProviderAdapter(
    api_key="anthropic-test-api-key",
    client=fake_client,  # type: ignore[arg-type]
)

request = LLMRequest(
    provider=LLMProvider.ANTHROPIC,
    model="claude-test-model",
    prompt="Generate a response.",
    system_prompt="You are a helpful assistant.",
    temperature=0.4,
    max_output_tokens=500,
    timeout_seconds=45,
    prompt_version="v1",
)

response = adapter.create_operation(request)()

print("Content:", response.content)
print("Request ID:", response.provider_request_id)
print("Input tokens:", response.usage.input_tokens)
print("Output tokens:", response.usage.output_tokens)
print("Total tokens:", response.usage.total_tokens)

assert response.content == ("Claude normalized response")
assert response.provider_request_id == "message-001"
assert response.usage.input_tokens == 30
assert response.usage.output_tokens == 20
assert response.usage.total_tokens == 50
assert response.usage.estimated_cost_usd == 0.0
assert response.metadata["provider"] == "anthropic"
assert response.metadata["message_id"] == "message-001"
assert response.metadata["stop_reason"] == "end_turn"
assert response.metadata["json_mode"] is False
assert fake_client.timeout == 45


multi_block_response = SimpleNamespace(
    content=[
        SimpleNamespace(
            type="text",
            text="First ",
        ),
        SimpleNamespace(
            type="tool_use",
            text=None,
        ),
        SimpleNamespace(
            type="text",
            text="second.",
        ),
    ]
)

assert AnthropicProviderAdapter._extract_text(multi_block_response) == "First second."


response_without_usage = SimpleNamespace(
    usage=None,
)

empty_usage = AnthropicProviderAdapter._extract_usage(response_without_usage)

assert empty_usage.input_tokens == 0
assert empty_usage.output_tokens == 0
assert empty_usage.total_tokens == 0


try:
    AnthropicProviderAdapter(
        api_key=" ",
    )
except ValueError:
    print("Empty Anthropic API key successfully blocked.")
else:
    raise AssertionError("Empty Anthropic API key should fail.")


wrong_provider_request = LLMRequest(
    provider=LLMProvider.OPENAI,
    model="test-model",
    prompt="Test",
    prompt_version="v1",
)

try:
    adapter.create_operation(wrong_provider_request)
except ValueError:
    print("Wrong provider request successfully blocked.")
else:
    raise AssertionError("Anthropic adapter must reject " "non-Anthropic requests.")


print("Anthropic Provider tests completed successfully.")
