from __future__ import annotations

from src.agents.research_agent.agent import (
    ResearchAgent,
)
from src.services.llm.llm_service import (
    LLMServiceAttempt,
    LLMServiceResult,
)
from src.shared.llm.models import (
    LLMCallResult,
    LLMCallStatus,
    LLMProvider,
    LLMUsage,
)
from src.shared.llm.request import LLMRequest


class SuccessfulLLMService:
    """Small LLM service stub for the ResearchAgent test."""

    def generate(
        self,
        request: LLMRequest,
        *,
        estimated_cost_usd: float = 0.0,
        profile_ids: list[str] | None = None,
    ) -> LLMServiceResult:
        assert request.prompt_version == ("research_prompt_v2.0.0")

        assert "Hidden Underground Cities" in (request.prompt)

        assert estimated_cost_usd == 0.25

        assert profile_ids == [
            "openai-main",
            "gemini-backup",
        ]

        result = LLMCallResult(
            status=LLMCallStatus.SUCCESS,
            provider=LLMProvider.GEMINI,
            model="gemini-test-model",
            content=(
                "Underground cities were created for "
                "protection, survival, trade and refuge."
            ),
            usage=LLMUsage(
                input_tokens=100,
                output_tokens=50,
                total_tokens=150,
                estimated_cost_usd=0.10,
            ),
            provider_request_id="request-001",
            metadata={
                "profile_id": "gemini-backup",
            },
        )

        return LLMServiceResult(
            result=result,
            selected_profile_id="gemini-backup",
            attempted_profile_ids=[
                "openai-main",
                "gemini-backup",
            ],
            attempts=[
                LLMServiceAttempt(
                    attempt_number=1,
                    profile_id="openai-main",
                    provider_name="OpenAI",
                    model="openai-test-model",
                    status=(LLMCallStatus.PROVIDER_ERROR),
                    error_message=("Primary provider unavailable."),
                ),
                LLMServiceAttempt(
                    attempt_number=2,
                    profile_id="gemini-backup",
                    provider_name="Google Gemini",
                    model="gemini-test-model",
                    status=LLMCallStatus.SUCCESS,
                ),
            ],
            used_failover=True,
        )


agent = ResearchAgent(
    llm_service=SuccessfulLLMService(),  # type: ignore[arg-type]
    profile_ids=[
        "openai-main",
        "gemini-backup",
    ],
    estimated_cost_usd=0.25,
)

research = agent.research("Top 10 Hidden Underground Cities")

print("Topic:", research.topic)
print("Summary:", research.research_summary)
print("Status:", research.status)
print("Prompt version:", research.prompt_version)

assert research.topic == ("Top 10 Hidden Underground Cities")

assert "Underground cities" in (research.research_summary)

assert research.prompt_version == ("research_prompt_v2.0.0")

assert research.status.value == "under_review"

assert research.sources[0].title == (
    "LLM-generated research draft via " "gemini-backup"
)


try:
    agent.research(" ")
except ValueError:
    print("Empty research topic successfully blocked.")
else:
    raise AssertionError("Empty research topic should fail.")


try:
    ResearchAgent(
        llm_service=SuccessfulLLMService(),  # type: ignore[arg-type]
        estimated_cost_usd=-1.0,
    )
except ValueError:
    print("Negative research cost successfully blocked.")
else:
    raise AssertionError("Negative research cost should fail.")


print("Research Agent tests completed successfully.")
