from pydantic import ValidationError

from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest


request = LLMRequest(
    provider=LLMProvider.OPENAI,
    model=" test-model ",
    prompt=" Generate a structured response. ",
    system_prompt=" You are a helpful assistant. ",
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
    max_output_tokens=500,
    timeout_seconds=90,
    provider_profile_id=" openai-main ",
    prompt_version=" v1 ",
    metadata={
        "project_id": "project-001",
    },
)

print("Provider:", request.provider)
print("Model:", request.model)
print("JSON expected:", request.expect_json)
print("Profile:", request.provider_profile_id)

assert request.model == "test-model"
assert request.prompt == "Generate a structured response."
assert request.system_prompt == "You are a helpful assistant."
assert request.provider_profile_id == "openai-main"
assert request.prompt_version == "v1"
assert request.temperature == 0.4
assert request.max_output_tokens == 500
assert request.timeout_seconds == 90


plain_request = LLMRequest(
    provider=LLMProvider.GEMINI,
    model="gemini-test",
    prompt="Write a short summary.",
    prompt_version="v1",
)

assert plain_request.expect_json is False
assert plain_request.response_schema is None
assert plain_request.temperature == 0.7
assert plain_request.timeout_seconds == 60


try:
    LLMRequest(
        provider=LLMProvider.OPENAI,
        model="test-model",
        prompt="Test",
        prompt_version="v1",
        response_schema={
            "type": "object",
        },
    )
except ValidationError:
    print(
        "Schema without JSON mode successfully blocked."
    )
else:
    raise AssertionError(
        "response_schema must require expect_json."
    )


try:
    LLMRequest(
        provider=LLMProvider.OPENAI,
        model="test-model",
        prompt="Test",
        prompt_version="v1",
        temperature=3.0,
    )
except ValidationError:
    print("Invalid temperature successfully blocked.")
else:
    raise AssertionError(
        "Temperature above the limit should fail."
    )


try:
    LLMRequest(
        provider=LLMProvider.OPENAI,
        model=" ",
        prompt="Test",
        prompt_version="v1",
    )
except ValidationError:
    print("Empty model successfully blocked.")
else:
    raise AssertionError(
        "Empty model should fail."
    )


serialized = request.model_dump_json()
restored = LLMRequest.model_validate_json(serialized)

assert restored == request

print("LLM Request tests completed successfully.")