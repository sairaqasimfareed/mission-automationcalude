from __future__ import annotations

from src.models.approval import ApprovalPolicyConfig, HumanApprovalAction
from src.models.enums import ProductionMode, WorkflowStage
from src.models.manual_audio_requirement import (
    ManualAudioRequirement,
    ManualAudioRequirementType,
)
from src.models.script_quality_report import ScriptQualityReport, ScriptQualityStatus
from src.models.video_job import VideoJob
from src.services.approval_gate_service import ApprovalGateService
from src.services.project_header_service import ProjectHeaderService


def _job(**overrides: object) -> VideoJob:
    job = VideoJob(
        project_name="Test Project",
        channel_name="Test Channel",
        niche="test niche",
        topic="Test topic",
    )

    for field_name, value in overrides.items():
        setattr(job, field_name, value)

    return job


def test_summarize_reflects_project_name_and_production_mode() -> None:
    job = _job(production_mode=ProductionMode.QUICK)

    summary = ProjectHeaderService().summarize(job)

    assert summary.project_name == "Test Project"
    assert summary.production_mode == "quick"


def test_summarize_reflects_current_stage() -> None:
    job = _job(current_stage=WorkflowStage.RENDER)

    summary = ProjectHeaderService().summarize(job)

    assert summary.current_stage == "render"


def test_summarize_reflects_the_configured_approval_preset() -> None:
    job = _job(approval_policy=ApprovalPolicyConfig.full_auto())

    summary = ProjectHeaderService().summarize(job)

    assert summary.approval_mode == "Fully Automatic"


def test_next_approval_is_none_pending_by_default() -> None:
    job = _job()

    summary = ProjectHeaderService().summarize(job)

    assert summary.next_approval == "None pending"


def test_next_approval_names_the_pending_decision_point() -> None:
    job = _job(approval_policy=ApprovalPolicyConfig.manual_editorial())
    ApprovalGateService().gate(
        job=job, decision_point="research", stage="research", summary="x"
    )

    summary = ProjectHeaderService().summarize(job)

    assert summary.next_approval == "research"


def test_quality_state_not_checked_before_any_gate() -> None:
    job = _job()

    summary = ProjectHeaderService().summarize(job)

    assert summary.quality_state == "Not checked"


def test_quality_state_approved() -> None:
    job = _job(
        script_quality_report=ScriptQualityReport(
            topic="Test topic",
            genre_id="genre.default",
            status=ScriptQualityStatus.APPROVED_FOR_PRODUCTION,
            dimension_scores={},
            dimension_thresholds={},
        )
    )

    summary = ProjectHeaderService().summarize(job)

    assert summary.quality_state == "Approved"


def test_quality_state_needs_revision() -> None:
    job = _job(
        script_quality_report=ScriptQualityReport(
            topic="Test topic",
            genre_id="genre.default",
            status=ScriptQualityStatus.NEEDS_REVISION,
            dimension_scores={},
            dimension_thresholds={},
        )
    )

    summary = ProjectHeaderService().summarize(job)

    assert summary.quality_state == "needs revision"


def test_budget_state_ok_with_no_manual_requirements() -> None:
    job = _job()

    summary = ProjectHeaderService().summarize(job)

    assert summary.budget_state == "OK"


def test_budget_state_reports_unfulfilled_manual_requirements() -> None:
    job = _job(
        manual_audio_requirements=[
            ManualAudioRequirement(
                requirement_type=ManualAudioRequirementType.MUSIC,
                reason="No music provider is configured.",
                instructions="Configure a music provider.",
            )
        ]
    )

    summary = ProjectHeaderService().summarize(job)

    assert summary.budget_state == "1 manual requirement(s)"


def test_budget_state_ignores_fulfilled_requirements() -> None:
    job = _job(
        manual_audio_requirements=[
            ManualAudioRequirement(
                requirement_type=ManualAudioRequirementType.MUSIC,
                reason="No music provider is configured.",
                instructions="Configure a music provider.",
                fulfilled=True,
                provided_file="music.mp3",
            )
        ]
    )

    summary = ProjectHeaderService().summarize(job)

    assert summary.budget_state == "OK"


def test_automation_state_automated_under_full_auto() -> None:
    job = _job(approval_policy=ApprovalPolicyConfig.full_auto())

    summary = ProjectHeaderService().summarize(job)

    assert summary.automation_state == "Automated"


def test_automation_state_manual_under_manual_editorial() -> None:
    job = _job(approval_policy=ApprovalPolicyConfig.manual_editorial())

    summary = ProjectHeaderService().summarize(job)

    assert summary.automation_state == "Manual"


def test_automation_state_waiting_for_you_when_a_gate_is_pending() -> None:
    job = _job(approval_policy=ApprovalPolicyConfig.full_auto())
    ApprovalGateService().gate(
        job=job,
        decision_point="research",
        stage="research",
        summary="x",
        confidence=0.1,
    )

    summary = ProjectHeaderService().summarize(job)

    assert summary.automation_state == "Waiting for you"


def test_automation_state_under_custom_review_with_nothing_pending() -> None:
    job = _job(approval_policy=ApprovalPolicyConfig.review_critical_stages())

    summary = ProjectHeaderService().summarize(job)

    assert summary.automation_state == "Automated (with review points)"


def test_readiness_state_is_blocked_for_a_bare_job() -> None:
    job = _job()

    summary = ProjectHeaderService().summarize(job)

    assert summary.readiness_state == "blocked"


def test_resolving_a_pending_decision_clears_waiting_for_you() -> None:
    job = _job(approval_policy=ApprovalPolicyConfig.manual_editorial())
    gate_service = ApprovalGateService()
    gate_service.gate(job=job, decision_point="research", stage="research", summary="x")

    gate_service.resolve(
        job=job, decision_point="research", action=HumanApprovalAction.APPROVE
    )

    summary = ProjectHeaderService().summarize(job)

    assert summary.next_approval == "None pending"
    assert summary.automation_state != "Waiting for you"
