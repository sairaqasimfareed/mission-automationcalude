from __future__ import annotations

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


def _research() -> ResearchResult:
    return ResearchResult(
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


def _script(research: ResearchResult) -> Script:
    return Script(
        title=research.topic,
        content="Beneath ordinary streets, entire cities once existed in silence.",
        prompt_version="script_prompt_v1.0.0",
        word_count=9,
        estimated_duration_seconds=4,
        status=ScriptStatus.APPROVED,
        claude_review_status=ScriptReviewStatus.APPROVED,
    )


def _originality(script: Script) -> OriginalityResult:
    return OriginalityResult(
        script_id=str(script.id),
        originality_score=88,
        human_value_score=83,
        hook_strength_score=90,
        status=OriginalityStatus.APPROVED,
    )


def _policy() -> PolicyComplianceReport:
    return PolicyComplianceReport(
        source_mode=ProductionMode.PREMIUM,
        upload_readiness=True,
        youtube_monetization_risk=RiskLevel.LOW,
        facebook_monetization_risk=RiskLevel.LOW,
    )


def _job_with_full_pipeline_state() -> VideoJob:
    research = _research()
    script = _script(research)
    originality = _originality(script)

    return VideoJob(
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
        policy_report=_policy(),
    )


def test_video_job_stores_every_pipeline_stage_result() -> None:
    job = _job_with_full_pipeline_state()

    assert job.research is not None
    assert job.script is not None
    assert job.originality_review is not None
    assert job.policy_report is not None


def test_video_job_preserves_the_supplied_topic_and_project_fields() -> None:
    job = _job_with_full_pipeline_state()

    assert job.project_name == "Mission Automation"
    assert job.channel_name == "Beyond the Ninth"
    assert job.niche == "Mystery and Hidden Places"
    assert job.topic == "Top 10 Hidden Underground Cities"
    assert job.platform == Platform.YOUTUBE
    assert job.production_mode == ProductionMode.PREMIUM
    assert job.current_stage == WorkflowStage.ORIGINALITY_REVIEW


def test_video_job_research_reflects_its_approval_status() -> None:
    job = _job_with_full_pipeline_state()

    assert job.research is not None
    assert job.research.status == ResearchStatus.APPROVED


def test_video_job_script_reflects_its_approval_status() -> None:
    job = _job_with_full_pipeline_state()

    assert job.script is not None
    assert job.script.status == ScriptStatus.APPROVED


def test_video_job_originality_review_reflects_its_approval_status() -> None:
    job = _job_with_full_pipeline_state()

    assert job.originality_review is not None
    assert job.originality_review.status == OriginalityStatus.APPROVED


def test_video_job_policy_report_marks_upload_readiness() -> None:
    job = _job_with_full_pipeline_state()

    assert job.policy_report is not None
    assert job.policy_report.upload_readiness is True


def test_video_job_pipeline_fields_default_to_none() -> None:
    job = VideoJob(
        project_name="Test Project",
        channel_name="Test Channel",
        niche="test niche",
        topic="Test topic",
    )

    assert job.research is None
    assert job.script is None
    assert job.originality_review is None
    assert job.policy_report is None
