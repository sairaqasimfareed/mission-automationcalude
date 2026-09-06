from __future__ import annotations

from typing import Any

from src.models.approval import ApprovalDecision, HumanApprovalAction
from src.models.content_decision_record import ContentDecisionRecord, DecisionCategory
from src.models.video_job import VideoJob
from src.services.approval_service import ApprovalService


class ApprovalGateService:
    """
    Resolves one content-pipeline stage's completion against the job's
    configured ApprovalPolicyConfig and records the outcome as an
    append-only ContentDecisionRecord.

    This is the runtime piece ApprovalPolicyConfig and ApprovalService
    were built for but never wired together: a gated stage's
    decision_point is looked up in job.approval_policy, resolved
    through ApprovalService.open_decision(), and the result both
    returned (so a caller like ContentIntelligencePipeline.run_all()
    can decide whether to keep going) and preserved in
    job.content_decisions - append-only, so a restart never loses track
    of what was pending or how it was resolved.
    """

    def __init__(self, *, approval_service: ApprovalService | None = None) -> None:
        self.approval_service = approval_service or ApprovalService()

    def gate(
        self,
        *,
        job: VideoJob,
        decision_point: str,
        stage: str,
        summary: str,
        ai_recommendation: str | None = None,
        confidence: float | None = None,
        warnings: list[str] | None = None,
    ) -> ApprovalDecision:
        """Open (and record) one approval decision for a stage that just completed."""

        policy = job.approval_policy.policy_for(decision_point)

        decision = self.approval_service.open_decision(
            decision_point=decision_point,
            policy=policy,
            ai_recommendation=ai_recommendation,
            confidence=confidence,
            warnings=warnings,
        )

        job.content_decisions.append(
            ContentDecisionRecord(
                stage=stage,
                summary=summary,
                approval=decision,
                category=DecisionCategory.APPROVAL,
            )
        )

        return decision

    def record_event(
        self,
        *,
        job: VideoJob,
        stage: str,
        summary: str,
        category: DecisionCategory,
        metadata: dict[str, Any] | None = None,
    ) -> ContentDecisionRecord:
        """
        Content Studio Redesign, Phase 18: append a non-approval
        activity-history entry (generation/invalidation/restore/lock/
        unlock) for a stage that has no approval gate of its own.

        This is the single place every pipeline/service call that
        wants to show up in the Activity History panel goes through,
        so `job.content_decisions` stays the one append-only ledger
        `gate()`/`resolve()` already established rather than a second
        history mechanism growing up beside it.
        """

        record = ContentDecisionRecord(
            stage=stage,
            summary=summary,
            category=category,
            metadata=metadata or {},
        )

        job.content_decisions.append(record)

        return record

    def resolve(
        self,
        *,
        job: VideoJob,
        decision_point: str,
        action: HumanApprovalAction,
        notes: str | None = None,
    ) -> ApprovalDecision:
        """
        Apply a human action to the latest pending decision for one
        decision point.

        Appends the resolution as a *new* history entry rather than
        mutating the pending one in place - the record of "this was
        pending, then a human approved it" is exactly what an
        append-only history is for.
        """

        pending_record = self._latest_record_for_point(
            job=job, decision_point=decision_point
        )

        if pending_record is None or pending_record.approval is None:
            raise ValueError(f"No decision found for '{decision_point}' to resolve.")

        if not pending_record.approval.requires_human_action:
            raise ValueError(
                f"The latest decision for '{decision_point}' is "
                f"'{pending_record.approval.state.value}', not pending."
            )

        resolved = self.approval_service.apply_human_action(
            pending_record.approval, action=action, notes=notes
        )

        job.content_decisions.append(
            ContentDecisionRecord(
                stage=pending_record.stage,
                summary=f"{pending_record.summary} -> {resolved.state.value}",
                approval=resolved,
                category=DecisionCategory.APPROVAL,
            )
        )

        return resolved

    @staticmethod
    def is_blocked(job: VideoJob, decision_point: str) -> bool:
        """Return whether the latest decision for one point is still pending."""

        record = ApprovalGateService._latest_record_for_point(
            job=job, decision_point=decision_point
        )

        return (
            record is not None
            and record.approval is not None
            and (record.approval.requires_human_action)
        )

    @staticmethod
    def latest_pending(job: VideoJob) -> ContentDecisionRecord | None:
        """Return the single most recent still-pending decision, if any."""

        pending = ApprovalGateService.all_pending(job)

        return pending[0] if pending else None

    @staticmethod
    def all_pending(job: VideoJob) -> list[ContentDecisionRecord]:
        """
        Return every decision point whose latest record is still
        pending - unlike latest_pending(), this doesn't stop at the
        first one, so a readiness check can report every open gate at
        once rather than only the earliest.
        """

        latest_by_point: dict[str, ContentDecisionRecord] = {}

        for record in job.content_decisions:
            if record.approval is not None:
                latest_by_point[record.approval.decision_point] = record

        return [
            record
            for record in latest_by_point.values()
            if record.approval is not None and record.approval.requires_human_action
        ]

    @staticmethod
    def _latest_record_for_point(
        *, job: VideoJob, decision_point: str
    ) -> ContentDecisionRecord | None:
        normalized = decision_point.strip().lower()

        for record in reversed(job.content_decisions):
            if (
                record.approval is not None
                and record.approval.decision_point == normalized
            ):
                return record

        return None
