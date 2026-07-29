from src.models.enums import Platform, ProductionMode
from src.models.originality import (
    OriginalityResult,
    OriginalityStatus,
)
from src.models.research import (
    ResearchResult,
    ResearchStatus,
)
from src.models.script import (
    Script,
    ScriptReviewStatus,
    ScriptStatus,
)
from src.models.video_job import VideoJob
from src.services.quality_gate import QualityGate

research = ResearchResult(
    topic="Top 10 Hidden Underground Cities",
    research_summary=(
        "Underground cities were built for protection, survival, and trade."
    ),
    key_facts=[
        "Several underground cities contain homes.",
        "Many were built for protection.",
    ],
    prompt_version="research_prompt_v1.0.0",
    status=ResearchStatus.APPROVED,
)

script = Script(
    title=research.topic,
    content=("Beneath ordinary streets, entire cities once existed in silence."),
    prompt_version="script_prompt_v1.0.0",
    word_count=9,
    estimated_duration_seconds=4,
    status=ScriptStatus.APPROVED,
    claude_review_status=ScriptReviewStatus.APPROVED,
)

originality = OriginalityResult(
    script_id=str(script.id),
    originality_score=88,
    human_value_score=83,
    hook_strength_score=90,
    status=OriginalityStatus.APPROVED,
)

job = VideoJob(
    project_name="Mission Automation",
    channel_name="Beyond the Ninth",
    niche="Mystery and Hidden Places",
    topic=research.topic,
    platform=Platform.YOUTUBE,
    production_mode=ProductionMode.PREMIUM,
    research=research,
    script=script,
    originality_review=originality,
)

gate = QualityGate()
result = gate.evaluate(job)

print("Errors:", result.errors)
print("Warnings:", result.warnings)

assert result.errors == []
assert result.warnings == []

print("Quality Gate tests completed successfully.")
