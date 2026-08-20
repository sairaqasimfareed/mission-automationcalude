from __future__ import annotations

from collections.abc import Callable

from src.models.approval import ApprovalPolicyConfig

# Named presets a user picks from, rather than editing 11 individual
# AUTO/REVIEW/MANUAL fields by hand - per-decision-point overrides
# remain possible via ApprovalPolicyConfig directly, just not through
# any settings panel yet.
APPROVAL_MODE_PRESETS: dict[str, Callable[[], ApprovalPolicyConfig]] = {
    "Fully Automatic": ApprovalPolicyConfig.full_auto,
    "Custom Approval": ApprovalPolicyConfig.review_critical_stages,
    "Approve Every Step": ApprovalPolicyConfig.manual_editorial,
}


_APPROVAL_FIELDS_TO_COMPARE = {"id", "created_at", "updated_at"}


def approval_mode_label(policy: ApprovalPolicyConfig) -> str:
    """
    Return the preset label matching one policy, or "Custom Approval"
    as a safe fallback for a hand-edited policy that does not match
    any of the three named presets exactly.

    Compares only the AUTO/REVIEW/MANUAL fields - every
    ApprovalPolicyConfig also carries its own id/created_at/
    updated_at (MissionBaseModel), which would make two otherwise-
    identical policies compare unequal by plain `==`.

    Shared between Content Studio's settings panel and the project
    header, so both surfaces describe the same policy the same way.
    """

    policy_fields = policy.model_dump(exclude=_APPROVAL_FIELDS_TO_COMPARE)

    for label, factory in APPROVAL_MODE_PRESETS.items():
        preset_fields = factory().model_dump(exclude=_APPROVAL_FIELDS_TO_COMPARE)

        if policy_fields == preset_fields:
            return label

    return "Custom Approval"
