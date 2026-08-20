from src.shared.llm.models import (
    LLMCallResult,
    LLMCallStatus,
    LLMProvider,
    LLMUsage,
)

usage = LLMUsage(
    input_tokens=100,
    output_tokens=50,
    total_tokens=150,
    estimated_cost_usd=0.0025,
)

result = LLMCallResult(
    status=LLMCallStatus.SUCCESS,
    provider=LLMProvider.OPENAI,
    model="test-model",
    content="Generated content",
    usage=usage,
    provider_request_id="request-001",
)

print("Provider:", result.provider)
print("Status:", result.status)
print("Tokens:", result.usage.total_tokens)
print("Cost:", result.usage.estimated_cost_usd)

assert result.is_success is True
assert result.provider == LLMProvider.OPENAI
assert result.content == "Generated content"
assert result.usage.input_tokens == 100
assert result.usage.output_tokens == 50
assert result.usage.total_tokens == 150
assert result.provider_request_id == "request-001"


failed_result = LLMCallResult(
    status=LLMCallStatus.PROVIDER_ERROR,
    provider=LLMProvider.GEMINI,
    model="gemini-test-model",
    error_message="Provider request failed.",
)

assert failed_result.is_success is False
assert failed_result.usage.total_tokens == 0
assert failed_result.usage.estimated_cost_usd == 0.0


serialized = result.model_dump_json()
restored = LLMCallResult.model_validate_json(serialized)

assert restored == result

print("LLM Models tests completed successfully.")
