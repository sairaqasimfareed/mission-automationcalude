from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from src.shared.llm.models import LLMProvider
from src.shared.llm.openai_provider import (
    OpenAIProviderAdapter,
)
from src.shared.llm.request import LLMRequest


class FakeResponses:
    def create(
        self,
        **kwargs: Any,
    ) -> Any:
        assert kwargs["model"] == "test-model"
        assert kwargs["input"] == "Generate a response."
        assert kwargs["instructions"] == (
            "You are a test assistant."
        )
        assert kwargs["max_output_tokens"] == 200

        return SimpleNamespace(
            id="response-001",
            output_text="OpenAI normalized response",
            usage=SimpleNamespace(
                input_tokens=20,
                output_tokens=10,
                total_tokens=30,
            ),
            _request_id="request-001",
        )


class FakeClient:
    def __init__(self) -> None:
        self.responses = FakeResponses()
        self.timeout: int | None = None

    def with_options(
        self,
        *,
        timeout: int,
    ) -> "FakeClient":
        self.timeout = timeout
        return self


fake_client = FakeClient()

adapter = OpenAIProviderAdapter(
    api_key="test-api-key",
    client=fake_client,  # type: ignore[arg-type]
)

request = LLMRequest(
    provider=LLMProvider.OPENAI,
    model="test-model",
    prompt="Generate a response.",
    system_prompt="You are a test assistant.",
    max_output_tokens=200,
    timeout_seconds=45,
    prompt_version="v1",
)

response = adapter.create_operation(
    request
)()

print("Content:", response.content)
print("Request ID:", response.provider_request_id)
print("Tokens:", response.usage.total_tokens)

assert response.content == "OpenAI normalized response"
assert response.provider_request_id == "request-001"
assert response.usage.input_tokens == 20
assert response.usage.output_tokens == 10
assert response.usage.total_tokens == 30
assert response.metadata["response_id"] == "response-001"
assert response.metadata["provider"] == "openai"
assert fake_client.timeout == 45


try:
    OpenAIProviderAdapter(
        api_key=" ",
    )
except ValueError:
    print("Empty API key successfully blocked.")
else:
    raise AssertionError(
        "Empty API key should fail."
    )


wrong_provider_request = LLMRequest(
    provider=LLMProvider.GEMINI,
    model="test-model",
    prompt="Test",
    prompt_version="v1",
)

try:
    adapter.create_operation(
        wrong_provider_request
    )
except ValueError:
    print(
        "Wrong provider request successfully blocked."
    )
else:
    raise AssertionError(
        "OpenAI adapter must reject non-OpenAI requests."
    )


print("OpenAI Provider tests completed successfully.")