from __future__ import annotations

import pytest

from src.models.approval import ApprovalPolicyConfig, ApprovalState, HumanApprovalAction
from src.models.video_job import VideoJob
from src.services.approval_gate_service import ApprovalGateService


def _job(**overrides: object) -> VideoJob:
    base: dict[str, object] = dict(
        project_name="Test Project",
        channel_name="Test Channel",
        niche="test niche",
        topic="Test topic",
    )
    base.update(overrides)
    return VideoJob(**base)


def test_gate_with_auto_policy_approves_immediately() -> None:
    job = _job(approval_policy=ApprovalPolicyConfig.full_auto())
    service = ApprovalGateService()

    decision = service.gate(
        job=job, decision_point="research", stage="research", summary="Research done."
    )

    assert decision.state == ApprovalState.APPROVED
    assert len(job.content_decisions) == 1
    assert job.content_decisions[0].approval is decision


def test_gate_with_review_policy_is_pending() -> None:
    job = _job(approval_policy=ApprovalPolicyConfig.manual_editorial())
    service = ApprovalGateService()

    decision = service.gate(
        job=job, decision_point="research", stage="research", summary="Research done."
    )

    assert decision.state == ApprovalState.PENDING


def test_gate_with_auto_policy_and_low_confidence_still_pends() -> None:
    job = _job(approval_policy=ApprovalPolicyConfig.full_auto())
    service = ApprovalGateService()

    decision = service.gate(
        job=job,
        decision_point="hook",
        stage="hooks",
        summary="Hook selected.",
        confidence=0.2,
    )

    assert decision.state == ApprovalState.PENDING


def test_is_blocked_false_before_any_decision() -> None:
    job = _job()

    assert ApprovalGateService.is_blocked(job, "research") is False


def test_is_blocked_true_after_a_pending_gate() -> None:
    job = _job(approval_policy=ApprovalPolicyConfig.manual_editorial())
    service = ApprovalGateService()

    service.gate(job=job, decision_point="research", stage="research", summary="x")

    assert ApprovalGateService.is_blocked(job, "research") is True
    assert ApprovalGateService.is_blocked(job, "hook") is False


def test_is_blocked_false_after_resolution() -> None:
    job = _job(approval_policy=ApprovalPolicyConfig.manual_editorial())
    service = ApprovalGateService()

    service.gate(job=job, decision_point="research", stage="research", summary="x")
    service.resolve(
        job=job, decision_point="research", action=HumanApprovalAction.APPROVE
    )

    assert ApprovalGateService.is_blocked(job, "research") is False


def test_resolve_approves_and_appends_a_new_history_entry() -> None:
    job = _job(approval_policy=ApprovalPolicyConfig.manual_editorial())
    service = ApprovalGateService()

    service.gate(job=job, decision_point="research", stage="research", summary="x")
    resolved = service.resolve(
        job=job,
        decision_point="research",
        action=HumanApprovalAction.APPROVE,
        notes="looks good",
    )

    assert resolved.state == ApprovalState.APPROVED
    assert resolved.resolved_notes == "looks good"
    assert len(job.content_decisions) == 2  # original PENDING record preserved


def test_resolve_rejects() -> None:
    job = _job(approval_policy=ApprovalPolicyConfig.manual_editorial())
    service = ApprovalGateService()

    service.gate(job=job, decision_point="research", stage="research", summary="x")
    resolved = service.resolve(
        job=job, decision_point="research", action=HumanApprovalAction.REJECT
    )

    assert resolved.state == ApprovalState.REJECTED


def test_resolve_raises_when_no_decision_exists() -> None:
    job = _job()
    service = ApprovalGateService()

    with pytest.raises(ValueError, match="No decision found"):
        service.resolve(
            job=job, decision_point="research", action=HumanApprovalAction.APPROVE
        )


def test_resolve_raises_when_already_resolved() -> None:
    job = _job(approval_policy=ApprovalPolicyConfig.manual_editorial())
    service = ApprovalGateService()

    service.gate(job=job, decision_point="research", stage="research", summary="x")
    service.resolve(
        job=job, decision_point="research", action=HumanApprovalAction.APPROVE
    )

    with pytest.raises(ValueError, match="not pending"):
        service.resolve(
            job=job, decision_point="research", action=HumanApprovalAction.APPROVE
        )


def test_latest_pending_returns_the_single_pending_record() -> None:
    job = _job(approval_policy=ApprovalPolicyConfig.manual_editorial())
    service = ApprovalGateService()

    service.gate(job=job, decision_point="research", stage="research", summary="r")

    pending = ApprovalGateService.latest_pending(job)

    assert pending is not None
    assert pending.stage == "research"


def test_latest_pending_returns_none_when_everything_resolved() -> None:
    job = _job(approval_policy=ApprovalPolicyConfig.manual_editorial())
    service = ApprovalGateService()

    service.gate(job=job, decision_point="research", stage="research", summary="r")
    service.resolve(
        job=job, decision_point="research", action=HumanApprovalAction.APPROVE
    )

    assert ApprovalGateService.latest_pending(job) is None


def test_latest_pending_ignores_an_earlier_resolved_point() -> None:
    job = _job(approval_policy=ApprovalPolicyConfig.manual_editorial())
    service = ApprovalGateService()

    service.gate(job=job, decision_point="research", stage="research", summary="r")
    service.resolve(
        job=job, decision_point="research", action=HumanApprovalAction.APPROVE
    )
    service.gate(job=job, decision_point="hook", stage="hooks", summary="h")

    pending = ApprovalGateService.latest_pending(job)

    assert pending is not None
    assert pending.stage == "hooks"
