from __future__ import annotations

from src.agents.script_agent.agent import ScriptAgent
from src.models.research import ResearchResult
from src.models.script import Script
from src.services.script_review_service import ScriptReviewService


class ScriptPipeline:
    """Generates a script and sends it through Claude-style review."""

    def __init__(self) -> None:
        self.script_agent = ScriptAgent()
        self.review_service = ScriptReviewService()

    def run(self, research: ResearchResult) -> Script:
        script = self.script_agent.generate(research)
        reviewed_script = self.review_service.review(script)

        return reviewed_script
