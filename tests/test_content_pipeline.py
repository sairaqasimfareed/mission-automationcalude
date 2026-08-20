from __future__ import annotations

from src.models.enums import (
    Platform,
    ProductionMode,
    WorkflowStage,
)
from src.models.research import (
    ResearchResult,
    ResearchSource,
    ResearchStatus,
)
from src.models.script import (
    Script,
    ScriptReviewStatus,
    ScriptStatus,
)
from src.models.video_job import VideoJob
from src.services.content_pipeline import ContentPipeline


class FakeResearchPipeline:
    """Fake research pipeline for ContentPipeline testing."""

    def run(
        self,
        topic: str,
    ) -> ResearchResult:
        return ResearchResult(
            topic=topic,
            research_summary=(
                "Underground cities were built for "
                "protection, storage, trade and survival."
            ),
            key_facts=[
                "Some underground cities contained homes.",
                "Many included food storage rooms.",
                "Ventilation shafts supported long stays.",
                "Defensive doors protected passageways.",
                "Some complexes contained wells and worship areas.",
            ],
            interesting_angles=[
                "How communities survived below ground.",
            ],
            potential_hooks=[
                "Entire cities once existed beneath ordinary streets.",
            ],
            risk_notes=[
                "Dates and population estimates require verification.",
            ],
            sources=[
                ResearchSource(
                    title="Test Historical Source",
                    confidence_score=95,
                )
            ],
            fact_confidence_score=92,
            prompt_version="research_prompt_v2.0.0",
            status=ResearchStatus.APPROVED,
        )


class FakeScriptPipeline:
    """Fake script pipeline for ContentPipeline testing."""

    def run(
        self,
        research: ResearchResult,
    ) -> Script:
        content = (
            "Beneath ordinary streets, entire cities once "
            "existed in silence. These underground complexes "
            "protected communities and helped them survive."
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
            status=ScriptStatus.APPROVED,
            claude_review_status=ScriptReviewStatus.APPROVED,
            claude_review_notes=[
                "Script structure is clear and suitable for production.",
            ],
        )


pipeline = ContentPipeline(
    llm_service=None,  # type: ignore[arg-type]
    research_pipeline=FakeResearchPipeline(),  # type: ignore[arg-type]
    script_pipeline=FakeScriptPipeline(),  # type: ignore[arg-type]
)

job = VideoJob(
    project_name="Hidden Underground Cities Project",
    channel_name="History Vault",
    niche="History Documentary",
    title="Hidden Underground Cities",
    topic="Top 10 Hidden Underground Cities",
    production_mode=ProductionMode.PREMIUM,
    platform=Platform.YOUTUBE,
)

result = pipeline.run(job)

print("Project:", result.project_name)
print("Current stage:", result.current_stage)
print("Research status:", result.research.status)
print("Script status:", result.script.status)
print("Scene count:", len(result.scenes))

assert result.research is not None
assert result.script is not None
assert result.originality_review is not None
assert len(result.scenes) > 0

assert result.research.status == ResearchStatus.APPROVED
assert result.script.status == ScriptStatus.APPROVED
assert result.script.claude_review_status == ScriptReviewStatus.APPROVED

assert result.current_stage == WorkflowStage.QUALITY_CHECK

print("Content Pipeline test completed successfully.")
