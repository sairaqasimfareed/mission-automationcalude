from __future__ import annotations

from src.models.research import (
    ResearchResult,
    ResearchSource,
    ResearchStatus,
)
from src.services.research_pipeline import ResearchPipeline


class FakeResearchAgent:
    """Fake research agent that returns review-ready research."""

    def research(
        self,
        topic: str,
    ) -> ResearchResult:
        return ResearchResult(
            topic=topic,
            research_summary=(
                "Underground cities were used for protection, "
                "trade, storage, worship, refuge and long-term "
                "survival across several historical periods."
            ),
            key_facts=[
                "Many underground cities included food storage rooms.",
                "Some complexes had ventilation shafts and wells.",
                "Several sites included defensive stone doors.",
                "Underground settlements could shelter large populations.",
                "Many complexes contained homes and places of worship.",
            ],
            interesting_angles=[
                "How people survived underground for long periods.",
                "Why entire communities were built below ground.",
            ],
            potential_hooks=[
                "Entire cities once existed beneath ordinary streets.",
                "Thousands of people could disappear underground.",
            ],
            risk_notes=[
                "Dates and population estimates require verification.",
            ],
            sources=[
                ResearchSource(
                    title="Verified Historical Source One",
                    confidence_score=95,
                ),
                ResearchSource(
                    title="Verified Historical Source Two",
                    confidence_score=90,
                ),
            ],
            fact_confidence_score=92,
            prompt_version="research_prompt_v2.0.0",
            status=ResearchStatus.UNDER_REVIEW,
        )


pipeline = ResearchPipeline(
    llm_service=None,  # type: ignore[arg-type]
    research_agent=FakeResearchAgent(),  # type: ignore[arg-type]
)

result = pipeline.run(
    "Top 10 Hidden Underground Cities"
)

print("Topic:", result.topic)
print("Final status:", result.status)
print("Review notes:", result.claude_review_notes)
print(
    "Suggested changes:",
    result.claude_suggested_changes,
)

assert result.topic == (
    "Top 10 Hidden Underground Cities"
)

assert result.status == ResearchStatus.APPROVED

assert len(result.claude_review_notes) > 0

assert len(result.key_facts) >= 5

assert result.fact_confidence_score >= 90

print(
    "Research pipeline test completed successfully."
)