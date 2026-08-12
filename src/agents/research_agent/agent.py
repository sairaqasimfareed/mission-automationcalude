from __future__ import annotations

from src.models.research import (
    ResearchResult,
    ResearchSource,
    ResearchStatus,
)
from src.services.llm.llm_service import LLMService
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest


class ResearchAgent:
    """Generates structured research through the central LLM service."""

    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError("Estimated research cost cannot be negative.")

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd

    def research(
        self,
        topic: str,
    ) -> ResearchResult:
        """Generate approved research for one topic."""

        normalized_topic = topic.strip()

        if not normalized_topic:
            raise ValueError("Research topic cannot be empty.")

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=(
                "Research the following topic for a long-form "
                "YouTube video:\n\n"
                f"{normalized_topic}"
            ),
            system_prompt=(
                "You are an expert research assistant for "
                "long-form YouTube videos. Produce accurate, "
                "original and clearly structured research. "
                "Flag claims that require additional verification."
            ),
            prompt_version="research_prompt_v2.0.0",
            metadata={
                "agent": "ResearchAgent",
                "workflow": "research",
                "topic": normalized_topic,
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

            raise RuntimeError("Research generation failed: " f"{error_message}")

        research_summary = (service_result.result.content or "").strip()

        if not research_summary:
            raise RuntimeError("Research provider returned empty content.")

        selected_profile_id = service_result.selected_profile_id or "unknown"

        return ResearchResult(
            topic=normalized_topic,
            research_summary=research_summary,
            key_facts=[
                ("Generated research must be reviewed " "before production."),
                (
                    f"Research summary length: "
                    f"{len(research_summary.split())} words."
                ),
            ],
            interesting_angles=[
                ("Identify the strongest unusual or " "little-known angle."),
            ],
            potential_hooks=[
                ("Open with the most surprising verified " "fact from the research."),
            ],
            risk_notes=[
                (
                    "Historical, scientific and statistical "
                    "claims should be independently verified."
                ),
            ],
            sources=[
                ResearchSource(
                    title=(
                        "LLM-generated research draft via " f"{selected_profile_id}"
                    ),
                    confidence_score=70,
                )
            ],
            fact_confidence_score=70,
            prompt_version=request.prompt_version,
            status=ResearchStatus.UNDER_REVIEW,
        )
