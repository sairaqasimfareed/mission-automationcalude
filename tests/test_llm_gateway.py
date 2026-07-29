from src.shared.llm.circuit_breaker import CircuitBreaker
from src.shared.llm.gateway import LLMGateway
from src.shared.llm.models import LLMCallStatus, LLMProvider
from src.shared.llm.retry import RetryConfig

gateway = LLMGateway(
    retry_config=RetryConfig(
        max_attempts=3,
        initial_delay_seconds=0.01,
        max_delay_seconds=0.02,
    ),
    circuit_breakers={
        LLMProvider.OPENAI: CircuitBreaker(
            failure_threshold=2,
            recovery_timeout_seconds=60,
        ),
        LLMProvider.ANTHROPIC: CircuitBreaker(
            failure_threshold=2,
            recovery_timeout_seconds=60,
        ),
    },
)


success_result = gateway.call(
    provider=LLMProvider.OPENAI,
    model="test-model",
    operation=lambda: "Normal text response",
)

print("Success status:", success_result.status)
print("Success content:", success_result.content)

assert success_result.status == LLMCallStatus.SUCCESS
assert success_result.is_success is True


json_result = gateway.call(
    provider=LLMProvider.ANTHROPIC,
    model="test-model",
    operation=lambda: '{"approved": true, "score": 91}',
    expect_json=True,
)

print("JSON status:", json_result.status)
print("Parsed JSON:", json_result.parsed_data)

assert json_result.status == LLMCallStatus.SUCCESS
assert json_result.parsed_data == {
    "approved": True,
    "score": 91,
}


malformed_result = gateway.call(
    provider=LLMProvider.ANTHROPIC,
    model="test-model",
    operation=lambda: "This is not valid JSON",
    expect_json=True,
)

print("Malformed status:", malformed_result.status)
print("Malformed error:", malformed_result.error_message)

assert malformed_result.status == LLMCallStatus.MALFORMED_RESPONSE


attempt_counter = {"count": 0}


def temporary_failure() -> str:
    attempt_counter["count"] += 1

    if attempt_counter["count"] < 3:
        raise TimeoutError("Temporary timeout.")

    return "Recovered successfully"


retry_result = gateway.call(
    provider=LLMProvider.OPENAI,
    model="test-model",
    operation=temporary_failure,
)

print("Retry status:", retry_result.status)
print("Retry count:", retry_result.retry_count)

assert retry_result.status == LLMCallStatus.SUCCESS
assert retry_result.retry_count == 2


print("LLM gateway tests completed successfully.")
