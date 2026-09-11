from __future__ import annotations

from src.agents.script_agent.agent import ScriptAgent
from src.models.research import ResearchResult
from src.models.script import Script
from src.services.llm.llm_service import LLMService
from src.services.script_review_service import (
    ScriptReviewService,
)


class ScriptPipeline:
    """Generates a script and sends it through review."""

    def __init__(
        self,
        *,
        llm_service: LLMService,
        script_agent: ScriptAgent | None = None,
        review_service: ScriptReviewService | None = None,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        self.script_agent = script_agent or ScriptAgent(
            llm_service=llm_service,
            profile_ids=profile_ids,
            estimated_cost_usd=estimated_cost_usd,
        )

        self.review_service = review_service or ScriptReviewService()

    def run(
        self,
        research: ResearchResult,
        *,
        target_duration_seconds: int | None = None,
    ) -> Script:
        """
        Generate a script and pass it through review.

        target_duration_seconds (2026-09-11 real fix, found live) is
        passed straight through to ScriptAgent.generate() - see that
        method's own docstring. None (the default) reproduces this
        method's exact prior behavior.
        """

        script = self.script_agent.generate(
            research,
            target_duration_seconds=target_duration_seconds,
        )

        return self.review_service.review(script)
