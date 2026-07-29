from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest

request = LLMRequest(
    provider=LLMProvider.OPENAI,
    model="test-model",
    prompt="Write a short test script.",
    system_prompt="You are a professional YouTube scriptwriter.",
    expect_json=False,
    temperature=0.7,
    max_output_tokens=1200,
    prompt_version="script_prompt_v1.0.0",
    metadata={
        "channel": "Beyond the Ninth",
        "job_id": "test-job-001",
    },
)

print("Provider:", request.provider)
print("Model:", request.model)
print("Prompt version:", request.prompt_version)
print("Expect JSON:", request.expect_json)
print("Metadata:", request.metadata)

assert request.provider == LLMProvider.OPENAI
assert request.prompt_version == "script_prompt_v1.0.0"
assert request.metadata["channel"] == "Beyond the Ninth"

print("LLM request model tests completed successfully.")
