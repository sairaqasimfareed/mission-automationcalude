from __future__ import annotations

from src.models.research import (
    ResearchResult,
    ResearchStatus,
)
from src.models.script import (
    Script,
    ScriptReviewStatus,
    ScriptStatus,
)
from src.services.script_pipeline import ScriptPipeline


class FakeScriptAgent:
    """Fake script agent for ScriptPipeline testing."""

    def generate(
        self,
        research: ResearchResult,
    ) -> Script:
        assert research.status == ResearchStatus.APPROVED

        content = (
            "Beneath ordinary streets, entire cities once "
            "existed in silence. These underground settlements "
            "protected communities from invasion and provided "
            "safe storage, shelter and long-term survival."
        )

        return Script(
            title=research.topic,
            content=content,
            prompt_version="script_prompt_v2.0.0",
            word_count=len(content.split()),
            estimated_duration_seconds=max(
                int(len(content.split()) / 2.3),
                1,
            ),
            status=ScriptStatus.UNDER_REVIEW,
        )


research = ResearchResult(
    topic="Top 10 Hidden Underground Cities",
    research_summary=(
        "Underground cities were built for protection, " "survival and trade."
    ),
    key_facts=[
        ("Several underground cities contained homes " "and storage rooms."),
        ("Many were designed to protect communities " "from invasion."),
        (
            "Ventilation systems allowed people to remain "
            "underground for extended periods."
        ),
        ("Some complexes included wells and places " "of worship."),
        ("Defensive stone doors protected important " "passageways."),
    ],
    prompt_version="research_prompt_v2.0.0",
    status=ResearchStatus.APPROVED,
)


pipeline = ScriptPipeline(
    llm_service=None,  # type: ignore[arg-type]
    script_agent=FakeScriptAgent(),  # type: ignore[arg-type]
)

script = pipeline.run(research)

print("Title:", script.title)
print("Final status:", script.status)
print("Claude review:", script.claude_review_status)
print("Review notes:", script.claude_review_notes)
print("Revision count:", script.revision_count)

assert script.title == ("Top 10 Hidden Underground Cities")

assert script.status == ScriptStatus.APPROVED

assert script.claude_review_status == ScriptReviewStatus.APPROVED

assert len(script.claude_review_notes) > 0

assert script.word_count > 0

assert script.prompt_version == ("script_prompt_v2.0.0")

print("Script pipeline test completed successfully.")
