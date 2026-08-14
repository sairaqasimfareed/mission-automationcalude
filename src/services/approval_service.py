from __future__ import annotations

from datetime import UTC, datetime

from src.models.approval import (
    ApprovalDecision,
    ApprovalPolicy,
    ApprovalState,
    HumanApprovalAction,
)

DEFAULT_CONFIDENCE_THRESHOLD = 0.7

_ACTIONS_APPROVING = {HumanApprovalAction.APPROVE}
_ACTIONS_REJECTING = {HumanApprovalAction.REJECT}


class ApprovalService:
    """
    Resolves one generic AUTO/REVIEW/MANUAL approval policy into a
    decision state, and applies human actions to pending decisions.

    This is the one shared human-in-the-loop abstraction new content-
    pipeline stages should depend on. AUTO only auto-continues when
    confidence is high and there are no critical warnings (spec
    section 56 - confidence-based escalation overrides an AUTO
    policy when the underlying result looks uncertain).
    """

    def open_decision(
        self,
        *,
        decision_point: str,
        policy: ApprovalPolicy,
        ai_recommendation: str | None = None,
        confidence: float | None = None,
        reasoning: list[str] | None = None,
        warnings: list[str] | None = None,
        alternatives: list[str] | None = None,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    ) -> ApprovalDecision:
        """
        Open one approval decision and resolve it as far as policy
        and confidence allow, without any human input yet.
        """

        resolved_warnings = list(warnings or [])

        state = self._resolve_initial_state(
            policy=policy,
            confidence=confidence,
            confidence_threshold=confidence_threshold,
            has_critical_warning=bool(resolved_warnings),
        )

        return ApprovalDecision(
            decision_point=decision_point,
            policy=policy,
            state=state,
            ai_recommendation=ai_recommendation,
            confidence=confidence,
            reasoning=list(reasoning or []),
            warnings=resolved_warnings,
            alternatives=list(alternatives or []),
        )

    def apply_human_action(
        self,
        decision: ApprovalDecision,
        *,
        action: HumanApprovalAction,
        notes: str | None = None,
    ) -> ApprovalDecision:
        """Apply one human action to a pending approval decision."""

        if not decision.requires_human_action:
            raise ValueError(
                "Only a pending approval decision can receive a "
                f"human action: '{decision.decision_point}' is "
                f"currently '{decision.state.value}'."
            )

        if action in _ACTIONS_APPROVING:
            new_state = ApprovalState.APPROVED
        elif action in _ACTIONS_REJECTING:
            new_state = ApprovalState.REJECTED
        else:
            new_state = ApprovalState.CHANGES_REQUESTED

        now = datetime.now(UTC)

        return decision.model_copy(
            update={
                "state": new_state,
                "resolved_action": action,
                "resolved_notes": notes,
                "resolved_at": now,
                "updated_at": now,
            }
        )

    @staticmethod
    def _resolve_initial_state(
        *,
        policy: ApprovalPolicy,
        confidence: float | None,
        confidence_threshold: float,
        has_critical_warning: bool,
    ) -> ApprovalState:
        if policy in (ApprovalPolicy.REVIEW, ApprovalPolicy.MANUAL):
            return ApprovalState.PENDING

        # AUTO
        if has_critical_warning:
            return ApprovalState.PENDING

        if confidence is not None and confidence < confidence_threshold:
            return ApprovalState.PENDING

        return ApprovalState.APPROVED
