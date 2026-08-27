from __future__ import annotations

from src.models.approval import ApprovalPolicyConfig
from src.models.audience_promise import AudiencePromise, PromiseStrength
from src.models.script_quality_report import ScriptQualityReport, ScriptQualityStatus
from src.models.script_version import ScriptVersion, ScriptVersionHistory
from src.models.video_job import VideoJob
from src.services.approval_gate_service import ApprovalGateService
from src.services.content_studio_journey_service import (
    ContentStudioJourneyService,
    JourneyCheckpointStatus,
)


def _job(**overrides: object) -> VideoJob:
    base: dict[str, object] = dict(
        project_name="Test Project",
        channel_name="Test Channel",
        niche="test niche",
        topic="Test topic",
        genre_id="genre.mystery",
    )
    base.update(overrides)
    return VideoJob(**base)


def _statuses(job: VideoJob) -> dict[str, JourneyCheckpointStatus]:
    checkpoints = ContentStudioJourneyService().compute(job)
    return {checkpoint.label: checkpoint.status for checkpoint in checkpoints}


def test_a_bare_job_has_every_checkpoint_not_started() -> None:
    statuses = _statuses(_job())

    assert all(
        status == JourneyCheckpointStatus.NOT_STARTED for status in statuses.values()
    )
    assert set(statuses) == {
        "Audience",
        "Research",
        "Angle",
        "Story",
        "Hook",
        "Script",
        "Quality",
        "Script Lock",
    }


def test_a_completed_unbgated_artifact_is_approved() -> None:
    job = _job(
        audience_promise=AudiencePromise(
            topic="Test topic",
            target_audience="general",
            platform="youtube",
            genre_id="genre.mystery",
            target_duration_seconds=180,
            intended_emotion="curiosity",
            central_curiosity="What happened?",
            primary_question="What happened?",
            viewer_benefit="Answers",
            expected_payoff="Resolution",
            promise_strength=PromiseStrength.STRONG,
            prompt_version="v1",
        ),
        approval_policy=ApprovalPolicyConfig.full_auto(),
    )

    statuses = _statuses(job)

    assert statuses["Audience"] == JourneyCheckpointStatus.APPROVED
    assert statuses["Research"] == JourneyCheckpointStatus.NOT_STARTED


def test_a_pending_gate_shows_waiting_not_approved() -> None:
    job = _job(
        audience_promise=AudiencePromise(
            topic="Test topic",
            target_audience="general",
            platform="youtube",
            genre_id="genre.mystery",
            target_duration_seconds=180,
            intended_emotion="curiosity",
            central_curiosity="What happened?",
            primary_question="What happened?",
            viewer_benefit="Answers",
            expected_payoff="Resolution",
            promise_strength=PromiseStrength.STRONG,
            prompt_version="v1",
        ),
        approval_policy=ApprovalPolicyConfig.manual_editorial(),
    )
    ApprovalGateService().gate(
        job=job,
        decision_point="content_strategy",
        stage="audience_promise",
        summary="x",
    )

    statuses = _statuses(job)

    assert statuses["Audience"] == JourneyCheckpointStatus.WAITING


def test_quality_needs_revision_is_distinct_from_waiting() -> None:
    job = _job(
        script_quality_report=ScriptQualityReport(
            topic="Test topic",
            genre_id="genre.mystery",
            status=ScriptQualityStatus.NEEDS_REVISION,
            dimension_scores={},
            dimension_thresholds={},
        )
    )

    statuses = _statuses(job)

    assert statuses["Quality"] == JourneyCheckpointStatus.NEEDS_REVISION


def test_quality_approved_for_production_is_approved() -> None:
    job = _job(
        script_quality_report=ScriptQualityReport(
            topic="Test topic",
            genre_id="genre.mystery",
            status=ScriptQualityStatus.APPROVED_FOR_PRODUCTION,
            dimension_scores={},
            dimension_thresholds={},
        )
    )

    statuses = _statuses(job)

    assert statuses["Quality"] == JourneyCheckpointStatus.APPROVED


def test_script_lock_not_started_without_a_version_history() -> None:
    statuses = _statuses(_job())

    assert statuses["Script Lock"] == JourneyCheckpointStatus.NOT_STARTED


def test_script_lock_waiting_when_history_exists_but_unlocked() -> None:
    from src.models.generated_script import GeneratedScript

    history = ScriptVersionHistory(
        topic="Test topic",
        versions=[
            ScriptVersion(
                version_number=1,
                script=GeneratedScript.model_construct(
                    segments=[], prompt_version="v1"
                ),
                change_summary="Initial draft.",
                locked=False,
            )
        ],
    )
    job = _job(script_version_history=history)

    statuses = _statuses(job)

    assert statuses["Script Lock"] == JourneyCheckpointStatus.WAITING


def test_script_lock_approved_when_locked() -> None:
    from src.models.generated_script import GeneratedScript

    history = ScriptVersionHistory(
        topic="Test topic",
        versions=[
            ScriptVersion(
                version_number=1,
                script=GeneratedScript.model_construct(
                    segments=[], prompt_version="v1"
                ),
                change_summary="Initial draft.",
                locked=True,
            )
        ],
    )
    job = _job(script_version_history=history)

    statuses = _statuses(job)

    assert statuses["Script Lock"] == JourneyCheckpointStatus.APPROVED


def test_checkpoints_are_in_pipeline_execution_order() -> None:
    checkpoints = ContentStudioJourneyService().compute(_job())

    assert [checkpoint.label for checkpoint in checkpoints] == [
        "Audience",
        "Research",
        "Angle",
        "Story",
        "Hook",
        "Script",
        "Quality",
        "Script Lock",
    ]
