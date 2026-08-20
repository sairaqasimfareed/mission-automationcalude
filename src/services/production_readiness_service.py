from __future__ import annotations

from src.models.asset_state import AssetWorkflowStatus
from src.models.blocker import Blocker, BlockerCode, BlockerSeverity
from src.models.production_readiness import ProductionReadinessReport, ReadinessState
from src.models.render_result import RenderStatus
from src.models.script_quality_report import ScriptQualityStatus
from src.models.video_job import VideoJob
from src.services.approval_gate_service import ApprovalGateService

_FAILED_ASSET_STATUSES = frozenset(
    {
        AssetWorkflowStatus.FAILED_RECOVERABLE,
        AssetWorkflowStatus.FAILED_FATAL,
        AssetWorkflowStatus.FAILED,
    }
)

_WAITING_ASSET_STATUSES = frozenset(
    {
        AssetWorkflowStatus.WAITING_FOR_USER_DECISION,
        AssetWorkflowStatus.WAITING_FOR_MANUAL_UPLOAD,
        AssetWorkflowStatus.WAITING_FOR_RECOVERY_DECISION,
        AssetWorkflowStatus.MANUAL_UPLOAD_REJECTED,
    }
)


class ProductionReadinessService:
    """
    One centralized answer to "is this project ready to render, ready
    to export, or done" - every GUI readiness indicator should consume
    this instead of re-deriving its own notion of "ready" from
    scattered VideoJob fields (docs/REMAINING_GAPS.md Phase 2).

    Read-only: inspects the job's already-persisted state and never
    mutates it. Blockers are recomputed fresh on every call rather
    than cached, since any prior call's blockers may already be stale
    by the time a caller reads them.
    """

    def evaluate(self, job: VideoJob) -> ProductionReadinessReport:
        blockers: list[Blocker] = [
            *self._content_blockers(job),
            *self._approval_blockers(job),
            *self._asset_blockers(job),
            *self._audio_blockers(job),
            *self._render_blockers(job),
            *self._policy_blockers(job),
            *self._staleness_blockers(job),
            *self._manual_audio_blockers(job),
        ]

        return ProductionReadinessReport(
            state=self._resolve_state(job, blockers),
            blockers=blockers,
        )

    def _content_blockers(self, job: VideoJob) -> list[Blocker]:
        blockers: list[Blocker] = []

        has_script = job.generated_script is not None or job.script is not None

        if not has_script:
            blockers.append(
                Blocker(
                    code=BlockerCode.SCRIPT_NOT_GENERATED,
                    stage="content_intelligence",
                    severity=BlockerSeverity.BLOCKING,
                    message="No script has been generated yet.",
                    affected_artifact="generated_script",
                    recovery_action="Run the content intelligence pipeline through the script stage.",
                )
            )

        if (
            job.script_quality_report is not None
            and job.script_quality_report.status == ScriptQualityStatus.NEEDS_REVISION
        ):
            blockers.append(
                Blocker(
                    code=BlockerCode.SCRIPT_NEEDS_REVISION,
                    stage="content_intelligence",
                    severity=BlockerSeverity.BLOCKING,
                    message="The script quality gate marked this script as needing revision.",
                    affected_artifact="generated_script",
                    recovery_action="Run the revision stage, then re-run the quality gate.",
                )
            )

        if not job.scenes:
            blockers.append(
                Blocker(
                    code=BlockerCode.SCENES_NOT_PLANNED,
                    stage="content_intelligence",
                    severity=BlockerSeverity.BLOCKING,
                    message="No scenes have been planned yet.",
                    affected_artifact="scenes",
                    recovery_action="Run scene planning.",
                )
            )

        return blockers

    def _approval_blockers(self, job: VideoJob) -> list[Blocker]:
        return [
            Blocker(
                code=BlockerCode.APPROVAL_PENDING,
                stage=record.stage,
                severity=BlockerSeverity.BLOCKING,
                message=f"'{record.approval.decision_point}' is waiting on a human decision.",
                affected_artifact=record.approval.decision_point,
                retryable=False,
                recovery_action="Approve or reject the pending decision.",
            )
            for record in ApprovalGateService.all_pending(job)
            if record.approval is not None
        ]

    def _asset_blockers(self, job: VideoJob) -> list[Blocker]:
        if not job.scenes:
            return []

        blockers: list[Blocker] = []
        states_by_scene_id = {state.scene_id: state for state in job.scene_asset_states}

        for scene in job.scenes:
            state = states_by_scene_id.get(str(scene.id))

            if state is None or state.status in (
                AssetWorkflowStatus.PENDING,
                AssetWorkflowStatus.SEARCHING_LOCAL,
                AssetWorkflowStatus.LOCAL_RESULTS_AVAILABLE,
                AssetWorkflowStatus.SEARCHING_STOCK,
                AssetWorkflowStatus.STOCK_RESULTS_AVAILABLE,
                AssetWorkflowStatus.ACQUIRING,
                AssetWorkflowStatus.RETRYING,
                AssetWorkflowStatus.VALIDATING_MANUAL_UPLOAD,
            ):
                blockers.append(
                    Blocker(
                        code=BlockerCode.ASSET_NOT_READY,
                        stage="asset_acquisition",
                        severity=BlockerSeverity.BLOCKING,
                        message=f"Scene {scene.scene_number} has no ready visual asset yet.",
                        affected_artifact=f"scene:{scene.id}",
                        recovery_action="Assign a manual upload or stock clip in Clip Workspace.",
                    )
                )
            elif state.status in _WAITING_ASSET_STATUSES:
                blockers.append(
                    Blocker(
                        code=BlockerCode.ASSET_NOT_READY,
                        stage="asset_acquisition",
                        severity=BlockerSeverity.BLOCKING,
                        message=(
                            f"Scene {scene.scene_number} is waiting on a user "
                            f"decision ({state.status.value})."
                        ),
                        affected_artifact=f"scene:{scene.id}",
                        recovery_action="Resolve the pending decision in Clip Workspace.",
                    )
                )
            elif (
                state.status in _FAILED_ASSET_STATUSES
                or state.active_failure is not None
            ):
                failure = state.active_failure
                blockers.append(
                    Blocker(
                        code=BlockerCode.ASSET_FAILURE,
                        stage="asset_acquisition",
                        severity=(
                            BlockerSeverity.BLOCKING
                            if failure is None or not failure.recoverable
                            else BlockerSeverity.WARNING
                        ),
                        message=(
                            failure.message
                            if failure is not None
                            else f"Scene {scene.scene_number} failed asset acquisition."
                        ),
                        affected_artifact=f"scene:{scene.id}",
                        retryable=failure.recoverable if failure is not None else True,
                        recovery_action="Retry or choose a different asset source.",
                    )
                )
            elif state.status == AssetWorkflowStatus.SKIPPED:
                blockers.append(
                    Blocker(
                        code=BlockerCode.ASSET_NOT_READY,
                        stage="asset_acquisition",
                        severity=BlockerSeverity.WARNING,
                        message=f"Scene {scene.scene_number} was explicitly skipped.",
                        affected_artifact=f"scene:{scene.id}",
                        recovery_action="Assign an asset if this scene should render after all.",
                    )
                )

        return blockers

    def _audio_blockers(self, job: VideoJob) -> list[Blocker]:
        if job.audio_timeline is None:
            return [
                Blocker(
                    code=BlockerCode.VOICE_NOT_READY,
                    stage="production_audio",
                    severity=BlockerSeverity.BLOCKING,
                    message="No audio timeline has been generated yet.",
                    affected_artifact="audio_timeline",
                    recovery_action="Generate voiceover in Production Audio.",
                )
            ]

        return []

    def _render_blockers(self, job: VideoJob) -> list[Blocker]:
        if job.video_timeline is None:
            return [
                Blocker(
                    code=BlockerCode.TIMELINE_NOT_BUILT,
                    stage="editing",
                    severity=BlockerSeverity.BLOCKING,
                    message="No editing timeline has been built yet.",
                    affected_artifact="video_timeline",
                    recovery_action="Build the editing timeline in Production Audio.",
                )
            ]

        if job.render_result is None:
            return [
                Blocker(
                    code=BlockerCode.RENDER_NOT_STARTED,
                    stage="render",
                    severity=BlockerSeverity.INFO,
                    message="Rendering has not started yet.",
                    affected_artifact="render_result",
                    recovery_action="Run render in Render Workspace.",
                )
            ]

        if (
            job.render_result.status == RenderStatus.FAILED
            or not job.render_result.success
        ):
            return [
                Blocker(
                    code=BlockerCode.RENDER_FAILED,
                    stage="render",
                    severity=BlockerSeverity.BLOCKING,
                    message=job.render_result.error_message
                    or "The last render failed.",
                    affected_artifact="render_result",
                    recovery_action="Retry the render in Render Workspace.",
                )
            ]

        return []

    def _policy_blockers(self, job: VideoJob) -> list[Blocker]:
        if job.policy_report is not None and not job.policy_report.upload_readiness:
            return [
                Blocker(
                    code=BlockerCode.POLICY_NOT_UPLOAD_READY,
                    stage="policy",
                    severity=BlockerSeverity.WARNING,
                    message="Policy review has not marked this project upload-ready.",
                    affected_artifact="policy_report",
                    recovery_action="Review policy findings in Quality Center.",
                )
            ]

        return []

    def _staleness_blockers(self, job: VideoJob) -> list[Blocker]:
        return [
            Blocker(
                code=BlockerCode.ARTIFACT_STALE,
                stage=record.triggered_by,
                severity=BlockerSeverity.BLOCKING,
                message=f"'{record.artifact}' is stale: {record.reason}",
                affected_artifact=record.artifact,
                recovery_action=f"Re-run the stage that produces '{record.artifact}'.",
            )
            for record in job.stale_artifacts
        ]

    def _manual_audio_blockers(self, job: VideoJob) -> list[Blocker]:
        return [
            Blocker(
                code=BlockerCode.MANUAL_AUDIO_REQUIRED,
                stage="production_audio",
                severity=BlockerSeverity.BLOCKING,
                message=(
                    f"{requirement.requirement_type.value} requires a manually "
                    f"supplied file: {requirement.reason}"
                ),
                affected_artifact=requirement.requirement_type.value,
                recovery_action=requirement.instructions,
            )
            for requirement in job.manual_audio_requirements
            if not requirement.fulfilled
        ]

    def _resolve_state(self, job: VideoJob, blockers: list[Blocker]) -> ReadinessState:
        blocking = [b for b in blockers if b.severity == BlockerSeverity.BLOCKING]

        if blocking:
            return ReadinessState.BLOCKED

        if job.render_result is not None and job.render_result.success:
            if job.policy_report is not None and job.policy_report.upload_readiness:
                return ReadinessState.COMPLETED

            return ReadinessState.READY_FOR_FINAL_EXPORT

        return ReadinessState.READY_FOR_RENDER
