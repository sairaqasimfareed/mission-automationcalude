from __future__ import annotations

from src.agents.script_agent.agent import ScriptAgent
from src.models.research import (
    ResearchResult,
    ResearchStatus,
)
from src.models.script import ScriptStatus
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
    """Small LLM service stub for the ScriptAgent test."""

    def generate(
        self,
        request: LLMRequest,
        *,
        estimated_cost_usd: float = 0.0,
        profile_ids: list[str] | None = None,
    ) -> LLMServiceResult:
        assert request.prompt_version == ("script_prompt_v2.0.0")

        assert "Hidden Underground Cities" in (request.prompt)

        assert estimated_cost_usd == 0.40

        assert profile_ids == [
            "openai-main",
            "gemini-backup",
        ]

        result = LLMCallResult(
            status=LLMCallStatus.SUCCESS,
            provider=LLMProvider.GEMINI,
            model="gemini-test-model",
            content=(
                "Beneath ordinary streets, entire cities "
                "once existed in silence. These hidden "
                "complexes protected communities from "
                "invasion and helped them survive."
            ),
            usage=LLMUsage(
                input_tokens=150,
                output_tokens=100,
                total_tokens=250,
                estimated_cost_usd=0.20,
            ),
            provider_request_id="request-script-001",
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


research = ResearchResult(
    topic="Top 10 Hidden Underground Cities",
    research_summary=(
        "Underground cities were built for protection, " "survival and trade."
    ),
    key_facts=[
        ("Several underground cities contain homes " "and storage rooms."),
        ("Many were designed to protect communities " "from invasion."),
    ],
    prompt_version="research_prompt_v2.0.0",
    status=ResearchStatus.APPROVED,
)


agent = ScriptAgent(
    llm_service=SuccessfulLLMService(),  # type: ignore[arg-type]
    profile_ids=[
        "openai-main",
        "gemini-backup",
    ],
    estimated_cost_usd=0.40,
)

script = agent.generate(research)

print("Title:", script.title)
print("Status:", script.status)
print("Prompt version:", script.prompt_version)
print("Word count:", script.word_count)
print("Content:", script.content)

assert script.title == ("Top 10 Hidden Underground Cities")

assert script.status == ScriptStatus.UNDER_REVIEW

assert script.prompt_version == ("script_prompt_v2.0.0")

assert script.word_count > 0

assert "Beneath ordinary streets" in (script.content)


unapproved_research = research.model_copy(
    update={
        "status": ResearchStatus.UNDER_REVIEW,
    }
)

try:
    agent.generate(unapproved_research)
except ValueError:
    print("Unapproved research successfully blocked.")
else:
    raise AssertionError("Unapproved research should fail.")


try:
    ScriptAgent(
        llm_service=SuccessfulLLMService(),  # type: ignore[arg-type]
        estimated_cost_usd=-1.0,
    )
except ValueError:
    print("Negative script cost successfully blocked.")
else:
    raise AssertionError("Negative script cost should fail.")


print("Script Agent tests completed successfully.")


# --- 2026-09-11 real fix, found live: a real 40-second test request
# produced a real 1578-second script, because generate() always asked
# for a "long-form" script regardless of the caller's actual target
# length. ---


class _RecordingLLMService:
    def __init__(self) -> None:
        self.last_request: LLMRequest | None = None

    def generate(
        self,
        request: LLMRequest,
        *,
        estimated_cost_usd: float = 0.0,
        profile_ids: list[str] | None = None,
    ) -> LLMServiceResult:
        self.last_request = request

        result = LLMCallResult(
            status=LLMCallStatus.SUCCESS,
            provider=LLMProvider.GEMINI,
            model="gemini-test-model",
            content="A short scripted response.",
            usage=LLMUsage(input_tokens=10, output_tokens=10, total_tokens=20),
        )

        return LLMServiceResult(result=result)


def test_generate_with_no_target_duration_asks_for_long_form() -> None:
    service = _RecordingLLMService()
    agent = ScriptAgent(llm_service=service)  # type: ignore[arg-type]

    agent.generate(research)

    assert service.last_request is not None
    assert "long-form" in service.last_request.prompt.lower()


def test_generate_with_a_target_duration_scopes_the_prompt() -> None:
    service = _RecordingLLMService()
    agent = ScriptAgent(llm_service=service)  # type: ignore[arg-type]

    agent.generate(research, target_duration_seconds=40)

    assert service.last_request is not None
    prompt = service.last_request.prompt
    assert "40 seconds" in prompt
    assert "do not write a long-form script" in prompt.lower()
    # ~2.3 words/second, matching Script.estimated_duration_seconds'
    # own formula - keeps the guidance and the script's own
    # self-reported duration consistent with each other.
    assert "92 words" in prompt
