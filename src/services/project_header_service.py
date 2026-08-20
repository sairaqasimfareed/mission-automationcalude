from __future__ import annotations

from src.desktop.approval_mode_labels import approval_mode_label
from src.models.script_quality_report import ScriptQualityStatus
from src.models.video_job import VideoJob
from src.services.approval_gate_service import ApprovalGateService
from src.services.production_readiness_service import ProductionReadinessService


class ProjectHeaderSummary:
    """
    The nine at-a-glance fields a persistent project header shows,
    each read from real, already-canonical backend state - never
    tracked separately from it. No field here is computed once and
    cached; ProjectHeaderService.summarize() derives all of them fresh
    from the job every call, matching ProductionReadinessService's own
    "never trust a stale verdict" convention.
    """

    def __init__(
        self,
        *,
        project_name: str,
        production_mode: str,
        current_stage: str,
        approval_mode: str,
        next_approval: str,
        quality_state: str,
        budget_state: str,
        automation_state: str,
        readiness_state: str,
    ) -> None:
        self.project_name = project_name
        self.production_mode = production_mode
        self.current_stage = current_stage
        self.approval_mode = approval_mode
        self.next_approval = next_approval
        self.quality_state = quality_state
        self.budget_state = budget_state
        self.automation_state = automation_state
        self.readiness_state = readiness_state


class ProjectHeaderService:
    """
    Computes ProjectHeaderSummary from a VideoJob - the single source
    every cross-tab header widget should read from, instead of each
    workspace deriving its own partial notion of "project status."

    Two fields are deliberately narrower proxies for what their name
    suggests, documented here rather than left silently ambiguous:

    - current_stage reads VideoJob.current_stage, which only the
      legacy ContentPipeline keeps updated - ContentIntelligencePipeline's
      12 stages don't touch it. For a project using the newer pipeline
      exclusively, this field can lag behind actual progress.
    - budget_state has no real per-project spend to report yet
      (Phase 7's budget gating tracks spend per ProviderProfile
      globally, not per VideoJob) - it reports whether any
      ManualAudioRequirement is unfulfilled instead, the closest
      real, job-level signal budget gating currently produces.
    """

    def __init__(
        self,
        *,
        readiness_service: ProductionReadinessService | None = None,
        approval_gate_service: ApprovalGateService | None = None,
    ) -> None:
        self.readiness_service = readiness_service or ProductionReadinessService()
        self.approval_gate_service = approval_gate_service or ApprovalGateService()

    def summarize(self, job: VideoJob) -> ProjectHeaderSummary:
        approval_mode = approval_mode_label(job.approval_policy)

        return ProjectHeaderSummary(
            project_name=job.project_name,
            production_mode=job.production_mode.value,
            current_stage=job.current_stage.value.replace("_", " "),
            approval_mode=approval_mode,
            next_approval=self._next_approval(job),
            quality_state=self._quality_state(job),
            budget_state=self._budget_state(job),
            automation_state=self._automation_state(job, approval_mode=approval_mode),
            readiness_state=self.readiness_service.evaluate(job).state.value.replace(
                "_", " "
            ),
        )

    @staticmethod
    def _next_approval(job: VideoJob) -> str:
        pending = ApprovalGateService.latest_pending(job)

        if pending is None or pending.approval is None:
            return "None pending"

        return pending.approval.decision_point.replace("_", " ")

    @staticmethod
    def _quality_state(job: VideoJob) -> str:
        report = job.script_quality_report

        if report is None:
            return "Not checked"

        if report.status == ScriptQualityStatus.APPROVED_FOR_PRODUCTION:
            return "Approved"

        return str(report.status.value).replace("_", " ")

    @staticmethod
    def _budget_state(job: VideoJob) -> str:
        unfulfilled = [
            requirement
            for requirement in job.manual_audio_requirements
            if not requirement.fulfilled
        ]

        if unfulfilled:
            return f"{len(unfulfilled)} manual requirement(s)"

        return "OK"

    @staticmethod
    def _automation_state(job: VideoJob, *, approval_mode: str) -> str:
        pending = ApprovalGateService.latest_pending(job)

        if pending is not None:
            return "Waiting for you"

        if approval_mode == "Fully Automatic":
            return "Automated"

        if approval_mode == "Approve Every Step":
            return "Manual"

        return "Automated (with review points)"
