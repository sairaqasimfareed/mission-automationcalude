from __future__ import annotations

from src.models.research import (
    ResearchResult,
    ResearchSource,
    ResearchStatus,
)
from src.shared.llm.dry_run_provider import DryRunProviderAdapter
from src.shared.llm.gateway import LLMGateway
from src.shared.llm.retry import RetryConfig


class ResearchAgent:
    """Generates structured research for a given topic."""

    def __init__(self) -> None:
        self.gateway = LLMGateway(
            retry_config=RetryConfig(
                max_attempts=2,
                initial_delay_seconds=0.01,
                max_delay_seconds=0.02,
            )
        )

        self.provider = DryRunProviderAdapter(
            response_text=(
                "Underground cities were historically built for "
                "protection, trade, and survival."
            )
        )

    def research(self, topic: str) -> ResearchResult:

        operation = self.provider.create_operation(
            model="dry-run-model",
            prompt=topic,
        )

        result = self.gateway.call(
            provider=self.provider.provider,
            model="dry-run-model",
            operation=operation,
        )

        return ResearchResult(
            topic=topic,
            research_summary=result.content or "",
            key_facts=[
                "Underground cities provided protection.",
                "Many contained homes and food storage.",
            ],
            interesting_angles=[
                "Why entire civilizations disappeared underground."
            ],
            potential_hooks=[
                "A hidden city existed beneath people's feet."
            ],
            risk_notes=[
                "Historical claims should be fact-checked."
            ],
            sources=[
                ResearchSource(
                    title="Dry Run Knowledge Base",
                    confidence_score=100,
                )
            ],
            fact_confidence_score=95,
            prompt_version="research_prompt_v1.0.0",
            status=ResearchStatus.APPROVED,
        )