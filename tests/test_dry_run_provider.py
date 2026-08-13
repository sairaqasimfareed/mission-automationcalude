import json

from src.shared.llm.dry_run_provider import (
    DryRunProviderAdapter,
)
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest

adapter = DryRunProviderAdapter()


text_request = LLMRequest(
    provider=LLMProvider.OPENAI,
    model="test-model",
    prompt="Write something.",
    prompt_version="v1",
)

text_response = adapter.create_operation(text_request)()

print("Text response:", text_response.content)

assert "Dry-run response" in text_response.content
assert text_response.usage.total_tokens == 20
assert text_response.provider_request_id == "dry-run-request"
assert text_response.metadata["dry_run"] is True


json_request = LLMRequest(
    provider=LLMProvider.GEMINI,
    model="gemini-test",
    prompt="Return JSON.",
    prompt_version="v1",
    expect_json=True,
)

json_response = adapter.create_operation(json_request)()

parsed = json.loads(json_response.content)

assert parsed["dry_run"] is True
assert parsed["provider"] == "gemini"
assert parsed["model"] == "gemini-test"
assert parsed["prompt_version"] == "v1"

override_request = LLMRequest(
    provider=LLMProvider.OPENAI,
    model="test-model",
    prompt="Write something specific.",
    prompt_version="v1",
    dry_run_response="CONCEPT: x\nHOOK: y\nPROMPT: z",
)

override_response = adapter.create_operation(override_request)()

print("Override response:", override_response.content)

assert override_response.content == "CONCEPT: x\nHOOK: y\nPROMPT: z"
assert override_response.usage.total_tokens == 20


print("Dry Run Provider tests completed successfully.")
