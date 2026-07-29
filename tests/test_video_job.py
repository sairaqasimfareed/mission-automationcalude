from src.models.enums import (
    Platform,
    ProductionMode,
    WorkflowStage,
)
from src.models.originality import (
    OriginalityResult,
    OriginalityStatus,
)
from src.models.policy import (
    PolicyComplianceReport,
    RiskLevel,
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

research = ResearchResult(
    topic="Top 10 Hidden Underground Cities",
    research_summary=(
        "Underground cities were built for protection, " "survival, and trade."
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
    content=("Beneath ordinary streets, entire cities once " "existed in silence."),
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

policy = PolicyComplianceReport(
    source_mode=ProductionMode.PREMIUM,
    upload_readiness=True,
    youtube_monetization_risk=RiskLevel.LOW,
    facebook_monetization_risk=RiskLevel.LOW,
)

job = VideoJob(
    project_name="Mission Automation",
    channel_name="Beyond the Ninth",
    niche="Mystery and Hidden Places",
    topic=research.topic,
    platform=Platform.YOUTUBE,
    production_mode=ProductionMode.PREMIUM,
    current_stage=WorkflowStage.ORIGINALITY_REVIEW,
    research=research,
    script=script,
    originality_review=originality,
    policy_report=policy,
)

print("Job ID:", job.id)
print("Topic:", job.topic)
print("Mode:", job.production_mode)
print("Stage:", job.current_stage)
print("Research:", job.research.status)
print("Script:", job.script.status)
print("Originality:", job.originality_review.status)
print("Upload ready:", job.policy_report.upload_readiness)

assert job.research is not None
assert job.script is not None
assert job.originality_review is not None
assert job.policy_report is not None
assert job.policy_report.upload_readiness is True

print("VideoJob model tests completed successfully.")
