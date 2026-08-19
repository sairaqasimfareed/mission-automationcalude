from __future__ import annotations

from src.models.approval import ApprovalPolicy, ApprovalPolicyConfig
from src.models.video_job import VideoJob


def _job(**overrides: object) -> VideoJob:
    base: dict[str, object] = dict(
        project_name="Test Project",
        channel_name="Test Channel",
        niche="test niche",
        topic="Test topic",
    )
    base.update(overrides)
    return VideoJob(**base)


def test_default_approval_policy_matches_review_critical_stages() -> None:
    job = _job()
    base_fields = {"id", "created_at", "updated_at"}

    assert job.approval_policy.model_dump(
        exclude=base_fields
    ) == ApprovalPolicyConfig.review_critical_stages().model_dump(exclude=base_fields)


def test_approval_policy_can_be_set_to_full_auto() -> None:
    job = _job(approval_policy=ApprovalPolicyConfig.full_auto())

    assert job.approval_policy.policy_for("publishing") == ApprovalPolicy.AUTO


def test_approval_policy_can_be_set_to_manual_editorial() -> None:
    job = _job(approval_policy=ApprovalPolicyConfig.manual_editorial())

    assert job.approval_policy.policy_for("topic") == ApprovalPolicy.MANUAL
