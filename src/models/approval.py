from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel


class ApprovalPolicy(str, Enum):
    """How much human involvement one decision point requires."""

    AUTO = "auto"
    REVIEW = "review"
    MANUAL = "manual"


class ApprovalState(str, Enum):
    """Lifecycle state of one approval-gated decision."""

    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"


class HumanApprovalAction(str, Enum):
    """Action a human may take on one pending approval decision."""

    APPROVE = "approve"
    EDIT = "edit"
    REJECT = "reject"
    REGENERATE = "regenerate"
    SELECT_ALTERNATIVE = "select_alternative"
    REQUEST_MORE_OPTIONS = "request_more_options"
    RETURN_TO_PREVIOUS = "return_to_previous"


class ApprovalDecision(MissionBaseModel):
    """
    One approval-gated decision point in the content pipeline.

    This is the single generic approval record every content-pipeline
    stage should depend on, instead of each stage inventing its own
    ad hoc PENDING/APPROVED status enum. Carries enough structured
    context (recommendation, confidence, warnings, alternatives) for
    a future GUI to display why a decision needs review, without any
    business service depending on GUI code.
    """

    decision_point: str
    policy: ApprovalPolicy
    state: ApprovalState = ApprovalState.NOT_REQUIRED

    ai_recommendation: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    reasoning: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    alternatives: list[str] = Field(default_factory=list)

    resolved_action: HumanApprovalAction | None = None
    resolved_notes: str | None = None
    resolved_at: datetime | None = None

    @field_validator("decision_point")
    @classmethod
    def clean_decision_point(cls, value: str) -> str:
        cleaned = value.strip().lower()

        if not cleaned:
            raise ValueError("Approval decision point cannot be empty.")

        return cleaned

    @property
    def is_resolved(self) -> bool:
        """Return whether this decision has a final outcome."""

        return self.state in {
            ApprovalState.APPROVED,
            ApprovalState.REJECTED,
            ApprovalState.CHANGES_REQUESTED,
        }

    @property
    def requires_human_action(self) -> bool:
        """Return whether a human must act before this can proceed."""

        return self.state == ApprovalState.PENDING


class ApprovalPolicyConfig(MissionBaseModel):
    """
    Per-project approval policy, one entry per pipeline decision
    point.

    Defaults follow the conservative posture the content-intelligence
    specification recommends: cheap/reversible steps default to AUTO,
    creative/expensive/public-facing steps default to REVIEW or
    MANUAL so a human sees them before they proceed.
    """

    topic: ApprovalPolicy = ApprovalPolicy.AUTO
    research: ApprovalPolicy = ApprovalPolicy.AUTO
    story_angle: ApprovalPolicy = ApprovalPolicy.REVIEW
    hook: ApprovalPolicy = ApprovalPolicy.AUTO
    final_script: ApprovalPolicy = ApprovalPolicy.REVIEW
    production_plan: ApprovalPolicy = ApprovalPolicy.AUTO
    budget: ApprovalPolicy = ApprovalPolicy.REVIEW
    final_preview: ApprovalPolicy = ApprovalPolicy.REVIEW
    publishing: ApprovalPolicy = ApprovalPolicy.MANUAL

    def policy_for(self, decision_point: str) -> ApprovalPolicy:
        """
        Return the configured policy for one decision point.

        Unknown decision points default to REVIEW rather than AUTO,
        so a misconfigured or future decision point fails toward
        asking a human instead of silently auto-continuing.
        """

        mapping: dict[str, ApprovalPolicy] = {
            "topic": self.topic,
            "research": self.research,
            "story_angle": self.story_angle,
            "hook": self.hook,
            "final_script": self.final_script,
            "production_plan": self.production_plan,
            "budget": self.budget,
            "final_preview": self.final_preview,
            "publishing": self.publishing,
        }

        return mapping.get(decision_point, ApprovalPolicy.REVIEW)
