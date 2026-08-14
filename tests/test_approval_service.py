from __future__ import annotations

from src.models.approval import (
    ApprovalDecision,
    ApprovalPolicy,
    ApprovalPolicyConfig,
    ApprovalState,
    HumanApprovalAction,
)
from src.services.approval_service import ApprovalService

service = ApprovalService()


# --- AUTO policy: high confidence, no warnings -> auto-approved ---

auto_clean = service.open_decision(
    decision_point="Story Angle",
    policy=ApprovalPolicy.AUTO,
    ai_recommendation="Angle 2: the missing logbook",
    confidence=0.92,
)

assert auto_clean.decision_point == "story angle"
assert auto_clean.state == ApprovalState.APPROVED
assert auto_clean.is_resolved is True
assert auto_clean.requires_human_action is False


# --- AUTO policy: low confidence -> escalates to PENDING ---

auto_low_confidence = service.open_decision(
    decision_point="research",
    policy=ApprovalPolicy.AUTO,
    confidence=0.4,
)

assert auto_low_confidence.state == ApprovalState.PENDING
assert auto_low_confidence.requires_human_action is True


# --- AUTO policy: critical warning present -> escalates to PENDING ---

auto_with_warning = service.open_decision(
    decision_point="research",
    policy=ApprovalPolicy.AUTO,
    confidence=0.99,
    warnings=["Two sources disagree on the timeline."],
)

assert auto_with_warning.state == ApprovalState.PENDING


# --- AUTO policy: no confidence signal at all -> approved (nothing to escalate on) ---

auto_no_signal = service.open_decision(
    decision_point="hook",
    policy=ApprovalPolicy.AUTO,
)

assert auto_no_signal.state == ApprovalState.APPROVED


# --- REVIEW policy: always PENDING regardless of confidence ---

review_high_confidence = service.open_decision(
    decision_point="final_script",
    policy=ApprovalPolicy.REVIEW,
    confidence=0.99,
)

assert review_high_confidence.state == ApprovalState.PENDING


# --- MANUAL policy: always PENDING ---

manual_decision = service.open_decision(
    decision_point="publishing",
    policy=ApprovalPolicy.MANUAL,
)

assert manual_decision.state == ApprovalState.PENDING


# --- Applying a human action: APPROVE ---

approved = service.apply_human_action(
    review_high_confidence,
    action=HumanApprovalAction.APPROVE,
    notes="Looks good.",
)

assert approved.state == ApprovalState.APPROVED
assert approved.resolved_action == HumanApprovalAction.APPROVE
assert approved.resolved_notes == "Looks good."
assert approved.resolved_at is not None
assert approved.is_resolved is True


# --- Applying a human action: REJECT ---

rejected = service.apply_human_action(
    manual_decision,
    action=HumanApprovalAction.REJECT,
)

assert rejected.state == ApprovalState.REJECTED


# --- Applying a human action: EDIT/REGENERATE/etc -> CHANGES_REQUESTED ---

for action in (
    HumanApprovalAction.EDIT,
    HumanApprovalAction.REGENERATE,
    HumanApprovalAction.SELECT_ALTERNATIVE,
    HumanApprovalAction.REQUEST_MORE_OPTIONS,
    HumanApprovalAction.RETURN_TO_PREVIOUS,
):
    pending = service.open_decision(
        decision_point="story_angle",
        policy=ApprovalPolicy.MANUAL,
    )

    changed = service.apply_human_action(pending, action=action)

    assert changed.state == ApprovalState.CHANGES_REQUESTED, action


# --- Cannot act on an already-resolved decision ---

try:
    service.apply_human_action(approved, action=HumanApprovalAction.APPROVE)
except ValueError as error:
    assert "pending" in str(error).lower()
else:
    raise AssertionError(
        "Applying a human action to an already-resolved decision should fail."
    )


# --- decision_point normalization + empty rejection ---

assert (
    service.open_decision(
        decision_point="  Final Script  ",
        policy=ApprovalPolicy.AUTO,
    ).decision_point
    == "final script"
)

try:
    ApprovalDecision(
        decision_point="   ",
        policy=ApprovalPolicy.AUTO,
    )
except ValueError:
    print("Empty decision point successfully blocked.")
else:
    raise AssertionError("Empty decision point should fail.")


# --- ApprovalPolicyConfig defaults + unknown key fails toward REVIEW ---

default_policy = ApprovalPolicyConfig()

assert default_policy.topic == ApprovalPolicy.AUTO
assert default_policy.research == ApprovalPolicy.AUTO
assert default_policy.story_angle == ApprovalPolicy.REVIEW
assert default_policy.hook == ApprovalPolicy.AUTO
assert default_policy.final_script == ApprovalPolicy.REVIEW
assert default_policy.production_plan == ApprovalPolicy.AUTO
assert default_policy.budget == ApprovalPolicy.REVIEW
assert default_policy.final_preview == ApprovalPolicy.REVIEW
assert default_policy.publishing == ApprovalPolicy.MANUAL

assert default_policy.policy_for("story_angle") == ApprovalPolicy.REVIEW
assert default_policy.policy_for("nonexistent_decision_point") == ApprovalPolicy.REVIEW


custom_policy = ApprovalPolicyConfig(research=ApprovalPolicy.MANUAL)

assert custom_policy.policy_for("research") == ApprovalPolicy.MANUAL
assert custom_policy.policy_for("topic") == ApprovalPolicy.AUTO


print("Approval Service tests completed successfully.")
