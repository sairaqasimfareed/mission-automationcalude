from src.shared.llm.models import (
    LLMCallResult,
    LLMCallStatus,
    LLMProvider,
)


success_result = LLMCallResult(
    status=LLMCallStatus.SUCCESS,
    provider=LLMProvider.OPENAI,
    model="test-openai-model",
    content="Test response",
    latency_seconds=1.25,
)

print("Success status:", success_result.status)
print("Is successful:", success_result.is_success)


blocked_result = LLMCallResult(
    status=LLMCallStatus.CIRCUIT_OPEN,
    provider=LLMProvider.ANTHROPIC,
    model="test-anthropic-model",
    error_message="Anthropic circuit breaker is open.",
)

print("Blocked status:", blocked_result.status)
print("Is successful:", blocked_result.is_success)
print("Error:", blocked_result.error_message)

print("LLM result model tests completed successfully.")