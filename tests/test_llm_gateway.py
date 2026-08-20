import json

from src.shared.llm.circuit_breaker import CircuitBreaker
from src.shared.llm.gateway import LLMGateway
from src.shared.llm.models import (
    LLMCallStatus,
    LLMProvider,
    LLMUsage,
)
from src.shared.llm.providers import LLMProviderResponse
from src.shared.llm.retry import RetryConfig

gateway = LLMGateway(
    retry_config=RetryConfig(
        max_attempts=2,
        initial_delay_seconds=0.01,
        max_delay_seconds=0.02,
    )
)


success_result = gateway.call(
    provider=LLMProvider.OPENAI,
    model="test-model",
    operation=lambda: LLMProviderResponse(
        content="Normal text response",
        usage=LLMUsage(
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
            estimated_cost_usd=0.001,
        ),
        provider_request_id="request-success-001",
        metadata={
            "source": "test",
        },
    ),
)

print("Success status:", success_result.status)
print("Success content:", success_result.content)
print("Success tokens:", success_result.usage.total_tokens)

assert success_result.status == LLMCallStatus.SUCCESS
assert success_result.is_success is True
assert success_result.content == "Normal text response"
assert success_result.usage.input_tokens == 10
assert success_result.usage.output_tokens == 5
assert success_result.usage.total_tokens == 15
assert success_result.usage.estimated_cost_usd == 0.001
assert success_result.provider_request_id == "request-success-001"
assert success_result.metadata["source"] == "test"


json_result = gateway.call(
    provider=LLMProvider.GEMINI,
    model="gemini-test-model",
    operation=lambda: LLMProviderResponse(
        content=json.dumps(
            {
                "title": "Test title",
                "approved": True,
            }
        ),
        usage=LLMUsage(
            input_tokens=20,
            output_tokens=10,
            total_tokens=30,
        ),
        provider_request_id="request-json-001",
    ),
    expect_json=True,
)

print("JSON status:", json_result.status)
print("Parsed data:", json_result.parsed_data)

assert json_result.status == LLMCallStatus.SUCCESS
assert json_result.parsed_data == {
    "title": "Test title",
    "approved": True,
}
assert json_result.usage.total_tokens == 30
assert json_result.provider_request_id == "request-json-001"


malformed_result = gateway.call(
    provider=LLMProvider.OPENAI,
    model="test-model",
    operation=lambda: LLMProviderResponse(
        content="This is not valid JSON",
        usage=LLMUsage(
            input_tokens=5,
            output_tokens=5,
            total_tokens=10,
        ),
        provider_request_id="request-malformed-001",
    ),
    expect_json=True,
)

print("Malformed status:", malformed_result.status)
print("Malformed error:", malformed_result.error_message)

assert malformed_result.status == LLMCallStatus.MALFORMED_RESPONSE
assert malformed_result.is_success is False
assert malformed_result.content == "This is not valid JSON"
assert malformed_result.usage.total_tokens == 10
assert malformed_result.provider_request_id == "request-malformed-001"


non_object_json_result = gateway.call(
    provider=LLMProvider.OPENAI,
    model="test-model",
    operation=lambda: LLMProviderResponse(
        content=json.dumps(
            [
                "item-1",
                "item-2",
            ]
        )
    ),
    expect_json=True,
)

assert non_object_json_result.status == LLMCallStatus.MALFORMED_RESPONSE
assert "Expected a JSON object" in (non_object_json_result.error_message or "")


attempt_counter = {
    "count": 0,
}


def retry_operation() -> LLMProviderResponse:
    attempt_counter["count"] += 1

    if attempt_counter["count"] == 1:
        raise TimeoutError("Temporary timeout.")

    return LLMProviderResponse(
        content="Recovered after retry",
        provider_request_id="request-retry-001",
    )


retry_result = gateway.call(
    provider=LLMProvider.ANTHROPIC,
    model="anthropic-test-model",
    operation=retry_operation,
)

print("Retry status:", retry_result.status)
print("Retry count:", retry_result.retry_count)

assert retry_result.status == LLMCallStatus.SUCCESS
assert retry_result.content == "Recovered after retry"
assert retry_result.retry_count == 1
assert retry_result.provider_request_id == "request-retry-001"


failing_gateway = LLMGateway(
    retry_config=RetryConfig(
        max_attempts=2,
        initial_delay_seconds=0.01,
        max_delay_seconds=0.02,
    )
)


def always_fail() -> LLMProviderResponse:
    raise TimeoutError("Provider unavailable.")


failure_result = failing_gateway.call(
    provider=LLMProvider.OPENAI,
    model="test-model",
    operation=always_fail,
)

print("Failure status:", failure_result.status)
print("Failure retries:", failure_result.retry_count)

assert failure_result.status == LLMCallStatus.RETRY_EXHAUSTED
assert failure_result.is_success is False
assert failure_result.retry_count == 1
assert failure_result.error_message is not None


open_breaker = CircuitBreaker(
    failure_threshold=1,
)

open_breaker.record_failure()

circuit_gateway = LLMGateway(
    circuit_breakers={
        LLMProvider.OPENAI: open_breaker,
        LLMProvider.ANTHROPIC: CircuitBreaker(),
        LLMProvider.GEMINI: CircuitBreaker(),
    }
)

circuit_result = circuit_gateway.call(
    provider=LLMProvider.OPENAI,
    model="test-model",
    operation=lambda: LLMProviderResponse(content="Should not execute"),
)

print("Circuit status:", circuit_result.status)

assert circuit_result.status == LLMCallStatus.CIRCUIT_OPEN
assert circuit_result.is_success is False


print("LLM Gateway tests completed successfully.")
