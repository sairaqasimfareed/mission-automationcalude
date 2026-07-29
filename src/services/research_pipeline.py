from __future__ import annotations

from src.agents.research_agent.agent import ResearchAgent
from src.models.research import ResearchResult, ResearchStatus
from src.services.research_review_service import ResearchReviewService


class ResearchPipeline:
    """Runs research generation and Claude-style review as one feature."""

    def __init__(self) -> None:
        self.research_agent = ResearchAgent()
        self.review_service = ResearchReviewService()

    def run(self, topic: str) -> ResearchResult:
        research = self.research_agent.research(topic)

        research.status = ResearchStatus.UNDER_REVIEW

        reviewed_research = self.review_service.review(research)

        return reviewed_research
