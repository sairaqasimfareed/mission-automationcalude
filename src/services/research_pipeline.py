from __future__ import annotations

from src.agents.research_agent.agent import ResearchAgent
from src.models.research import (
    ResearchResult,
    ResearchStatus,
)
from src.services.llm.llm_service import LLMService
from src.services.research_review_service import (
    ResearchReviewService,
)


class ResearchPipeline:
    """Runs research generation and review as one feature."""

    def __init__(
        self,
        *,
        llm_service: LLMService,
        research_agent: ResearchAgent | None = None,
        review_service: ResearchReviewService | None = None,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        self.research_agent = (
            research_agent
            or ResearchAgent(
                llm_service=llm_service,
                profile_ids=profile_ids,
                estimated_cost_usd=estimated_cost_usd,
            )
        )

        self.review_service = (
            review_service
            or ResearchReviewService()
        )

    def run(
        self,
        topic: str,
    ) -> ResearchResult:
        """Generate research and send it through review."""

        research = self.research_agent.research(topic)

        research.status = ResearchStatus.UNDER_REVIEW

        return self.review_service.review(research)