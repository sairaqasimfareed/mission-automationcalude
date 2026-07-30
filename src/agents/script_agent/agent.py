from __future__ import annotations

from src.models.research import (
    ResearchResult,
    ResearchStatus,
)
from src.models.script import (
    Script,
    ScriptStatus,
)
from src.services.llm.llm_service import LLMService
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest


class ScriptAgent:
    """Generates a draft script through the central LLM service."""

    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError(
                "Estimated script cost cannot be negative."
            )

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd

    def generate(
        self,
        research: ResearchResult,
    ) -> Script:
        """Generate one script from approved research."""

        if research.status != ResearchStatus.APPROVED:
            raise ValueError(
                "Script generation requires approved research."
            )

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=(
                "Write a long-form YouTube script using "
                "the following approved research:\n\n"
                f"Topic: {research.topic}\n\n"
                f"Research summary:\n"
                f"{research.research_summary}\n\n"
                "Key facts:\n"
                + "\n".join(
                    f"- {fact}"
                    for fact in research.key_facts
                )
            ),
            system_prompt=(
                "You are a professional long-form YouTube "
                "scriptwriter. Write an original, engaging, "
                "well-structured and channel-specific script. "
                "Do not invent unsupported factual claims."
            ),
            prompt_version="script_prompt_v2.0.0",
            metadata={
                "agent": "ScriptAgent",
                "workflow": "script",
                "research_id": str(research.id),
                "topic": research.topic,
            },
        )

        service_result = self.llm_service.generate(
            request,
            estimated_cost_usd=self.estimated_cost_usd,
            profile_ids=self.profile_ids,
        )

        if not service_result.is_success:
            error_message = (
                service_result.result.error_message
                or "All configured LLM providers failed."
            )

            raise RuntimeError(
                "Script generation failed: "
                f"{error_message}"
            )

        content = (
            service_result.result.content or ""
        ).strip()

        if not content:
            raise RuntimeError(
                "Script provider returned empty content."
            )

        word_count = len(content.split())

        return Script(
            title=research.topic,
            content=content,
            prompt_version=request.prompt_version,
            word_count=word_count,
            estimated_duration_seconds=max(
                int(word_count / 2.3),
                1,
            ),
            status=ScriptStatus.UNDER_REVIEW,
        )