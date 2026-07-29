from src.shared.llm.dry_run_provider import DryRunProviderAdapter
from src.shared.llm.gateway import LLMGateway
from src.shared.llm.models import LLMCallStatus
from src.shared.llm.retry import RetryConfig

gateway = LLMGateway(
    retry_config=RetryConfig(
        max_attempts=2,
        initial_delay_seconds=0.01,
        max_delay_seconds=0.02,
    )
)


text_adapter = DryRunProviderAdapter(response_text="This is a local dry-run script.")

text_operation = text_adapter.create_operation(
    model="dry-run-model",
    prompt="Write a test script.",
)

text_result = gateway.call(
    provider=text_adapter.provider,
    model="dry-run-model",
    operation=text_operation,
)

print("Text status:", text_result.status)
print("Text content:", text_result.content)

assert text_result.status == LLMCallStatus.SUCCESS
assert text_result.content == "This is a local dry-run script."


json_adapter = DryRunProviderAdapter(
    response_json={
        "approved": True,
        "notes": ["Script flow is clear."],
    }
)

json_operation = json_adapter.create_operation(
    model="dry-run-model",
    prompt="Review this test script.",
)

json_result = gateway.call(
    provider=json_adapter.provider,
    model="dry-run-model",
    operation=json_operation,
    expect_json=True,
)

print("JSON status:", json_result.status)
print("JSON data:", json_result.parsed_data)

assert json_result.status == LLMCallStatus.SUCCESS
assert json_result.parsed_data == {
    "approved": True,
    "notes": ["Script flow is clear."],
}

print("Dry-run provider tests completed successfully.")
