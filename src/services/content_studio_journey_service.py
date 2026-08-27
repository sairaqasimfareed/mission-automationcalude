from __future__ import annotations

from enum import Enum

from src.models.script_quality_report import ScriptQualityStatus
from src.models.video_job import VideoJob
from src.services.approval_gate_service import ApprovalGateService


class JourneyCheckpointStatus(str, Enum):
    """
    The 4 states the redesign's Content Studio journey strip shows per
    checkpoint. NOT_STARTED stands in for the redesign's own
    vocabulary's "Blocked" for a checkpoint whose prerequisite artifact
    doesn't exist yet - a checkpoint you simply haven't reached is a
    different, more common situation than one that's actively blocked
    by a real obstacle, and collapsing them into one label would hide
    that distinction from the operator.
    """

    NOT_STARTED = "not_started"
    WAITING = "waiting"
    NEEDS_REVISION = "needs_revision"
    APPROVED = "approved"


class JourneyCheckpoint:
    """One labeled step in the Content Studio production journey."""

    def __init__(self, *, label: str, status: JourneyCheckpointStatus) -> None:
        self.label = label
        self.status = status


class ContentStudioJourneyService:
    """
    Computes the Content Studio Redesign's Phase 3 "production
    journey" - a condensed, human-facing view over
    ContentIntelligencePipeline's 14 granular stages.

    Ordered to match the pipeline's actual execution order (Audience
    -> Research -> Angle -> Story -> Hook -> Script -> Quality ->
    Script Lock), not the redesign document's own listed order
    (Topic -> Audience -> Angle -> Research -> ...) - research runs
    before angle selection in the real pipeline (angles are generated
    from research findings), so showing Angle before Research would
    misrepresent what actually happens. Topic itself has no dedicated
    approval concept yet (it's a plain field set at project creation,
    with no Topic Intelligence workspace - see
    docs/CONTENT_STUDIO_REDESIGN_BASELINE.md, Phase 5) - deliberately
    left out of this journey rather than showing a permanently-"done"
    checkpoint for state that doesn't really exist.

    Recomputes fresh from the job every call, the same "never trust a
    stale verdict" convention ProductionReadinessService/
    ProjectHeaderService already establish - nothing here is cached.
    """

    def __init__(
        self,
        *,
        approval_gate_service: ApprovalGateService | None = None,
    ) -> None:
        self.approval_gate_service = approval_gate_service or ApprovalGateService()

    def compute(self, job: VideoJob) -> list[JourneyCheckpoint]:
        return [
            self._gated_checkpoint(
                "Audience", job.audience_promise is not None, job, "content_strategy"
            ),
            self._gated_checkpoint(
                "Research", job.research is not None, job, "research"
            ),
            self._gated_checkpoint(
                "Angle", job.selected_story_angle is not None, job, "story_angle"
            ),
            self._gated_checkpoint(
                "Story",
                job.story_blueprint is not None,
                job,
                "narrative_architecture",
            ),
            self._gated_checkpoint("Hook", job.selected_hook is not None, job, "hook"),
            self._gated_checkpoint(
                "Script", job.generated_script is not None, job, "final_script"
            ),
            self._quality_checkpoint(job),
            self._script_lock_checkpoint(job),
        ]

    def _gated_checkpoint(
        self,
        label: str,
        artifact_exists: bool,
        job: VideoJob,
        decision_point: str,
    ) -> JourneyCheckpoint:
        if not artifact_exists:
            return JourneyCheckpoint(
                label=label, status=JourneyCheckpointStatus.NOT_STARTED
            )

        if self.approval_gate_service.is_blocked(job, decision_point):
            return JourneyCheckpoint(
                label=label, status=JourneyCheckpointStatus.WAITING
            )

        return JourneyCheckpoint(label=label, status=JourneyCheckpointStatus.APPROVED)

    @staticmethod
    def _quality_checkpoint(job: VideoJob) -> JourneyCheckpoint:
        report = job.script_quality_report

        if report is None:
            return JourneyCheckpoint(
                label="Quality", status=JourneyCheckpointStatus.NOT_STARTED
            )

        if report.status == ScriptQualityStatus.NEEDS_REVISION:
            return JourneyCheckpoint(
                label="Quality", status=JourneyCheckpointStatus.NEEDS_REVISION
            )

        if report.status == ScriptQualityStatus.APPROVED_FOR_PRODUCTION:
            return JourneyCheckpoint(
                label="Quality", status=JourneyCheckpointStatus.APPROVED
            )

        # DRAFT / EDITORIAL_REVIEW - a report exists but hasn't reached
        # a final verdict yet.
        return JourneyCheckpoint(
            label="Quality", status=JourneyCheckpointStatus.WAITING
        )

    @staticmethod
    def _script_lock_checkpoint(job: VideoJob) -> JourneyCheckpoint:
        history = job.script_version_history

        if history is None:
            return JourneyCheckpoint(
                label="Script Lock", status=JourneyCheckpointStatus.NOT_STARTED
            )

        if history.is_locked:
            return JourneyCheckpoint(
                label="Script Lock", status=JourneyCheckpointStatus.APPROVED
            )

        return JourneyCheckpoint(
            label="Script Lock", status=JourneyCheckpointStatus.WAITING
        )
