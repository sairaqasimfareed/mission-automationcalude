from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from google.genai import types

from src.shared.llm.gemini_provider import (
    GeminiProviderAdapter,
)
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest


class FakeGeminiModels:
    """Fake Gemini models client used for unit tests."""

    def __init__(self) -> None:
        self.last_arguments: dict[str, Any] = {}

    def generate_content(
        self,
        **kwargs: Any,
    ) -> Any:
        self.last_arguments = kwargs

        assert kwargs["model"] == "gemini-test-model"
        assert kwargs["contents"] == "Generate JSON."

        config = kwargs["config"]

        assert isinstance(
            config,
            types.GenerateContentConfig,
        )

        assert config.system_instruction == ("You are a helpful assistant.")
        assert config.temperature == 0.4
        assert config.max_output_tokens == 300
        assert config.response_mime_type == ("application/json")
        assert config.response_schema is not None

        return SimpleNamespace(
            text='{"title":"Gemini response"}',
            response_id="gemini-response-001",
            usage_metadata=SimpleNamespace(
                prompt_token_count=25,
                candidates_token_count=15,
                total_token_count=40,
            ),
        )


class FakeGeminiClient:
    """Fake Gemini client."""

    def __init__(self) -> None:
        self.models = FakeGeminiModels()


fake_client = FakeGeminiClient()

adapter = GeminiProviderAdapter(
    api_key="gemini-test-api-key",
    client=fake_client,  # type: ignore[arg-type]
)

request = LLMRequest(
    provider=LLMProvider.GEMINI,
    model="gemini-test-model",
    prompt="Generate JSON.",
    system_prompt="You are a helpful assistant.",
    expect_json=True,
    response_schema={
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
            },
        },
        "required": [
            "title",
        ],
    },
    temperature=0.4,
    max_output_tokens=300,
    timeout_seconds=45,
    prompt_version="v1",
)

response = adapter.create_operation(request)()

print("Content:", response.content)
print("Request ID:", response.provider_request_id)
print("Input tokens:", response.usage.input_tokens)
print("Output tokens:", response.usage.output_tokens)
print("Total tokens:", response.usage.total_tokens)

assert response.content == ('{"title":"Gemini response"}')
assert response.provider_request_id == ("gemini-response-001")
assert response.usage.input_tokens == 25
assert response.usage.output_tokens == 15
assert response.usage.total_tokens == 40
assert response.usage.estimated_cost_usd == 0.0
assert response.metadata["provider"] == "gemini"
assert response.metadata["json_mode"] is True
assert response.metadata["response_id"] == ("gemini-response-001")


plain_request = LLMRequest(
    provider=LLMProvider.GEMINI,
    model="gemini-test-model",
    prompt="Write normal text.",
    prompt_version="v1",
)

plain_config = GeminiProviderAdapter._build_config(plain_request)

assert plain_config.response_mime_type is None
assert plain_config.response_schema is None
assert plain_config.temperature == 0.7


try:
    GeminiProviderAdapter(
        api_key=" ",
    )
except ValueError:
    print("Empty Gemini API key successfully blocked.")
else:
    raise AssertionError("Empty Gemini API key should fail.")


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
    raise AssertionError("Gemini adapter must reject non-Gemini requests.")


response_without_usage = SimpleNamespace(
    text="Response without usage",
    response_id=None,
    usage_metadata=None,
)

usage = GeminiProviderAdapter._extract_usage(response_without_usage)

assert usage.input_tokens == 0
assert usage.output_tokens == 0
assert usage.total_tokens == 0


print("Gemini Provider tests completed successfully.")
