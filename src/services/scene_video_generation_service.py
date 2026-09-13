from __future__ import annotations

import time
import uuid
from collections.abc import Callable

from src.models.asset_state import AssetUserDecision, SceneAssetState
from src.models.google_flow_generation import (
    GoogleFlowExecutionSettings,
    GoogleFlowGenerationAttempt,
    GoogleFlowGenerationState,
)
from src.models.scene import Scene
from src.models.scene_completeness import (
    SceneCompletenessEntry,
    SceneCompletenessReport,
)
from src.models.video_job import VideoJob
from src.providers.google_flow.locators import VERIFIED_DURATIONS_SECONDS
from src.services.google_flow_generation_ledger_service import (
    GoogleFlowGenerationLedgerService,
)
from src.services.google_flow_generation_orchestrator_service import (
    GoogleFlowGenerationOrchestratorService,
)
from src.services.scene_asset_video_clip_builder_service import (
    SceneAssetVideoClipBuilderService,
)
from src.services.scene_asset_workflow_service import SceneAssetWorkflowService
from src.services.scene_completeness_service import SceneCompletenessService
from src.services.scene_prompt_export_service import ScenePromptExportService

_POLLABLE_STATES = frozenset(
    {
        GoogleFlowGenerationState.SUBMITTED,
        GoogleFlowGenerationState.GENERATING,
    }
)

_PROMPT_VERSION = "scene_video_generation_prompt_v1.0.0"


class SceneVideoGenerationService:
    """
    Drives GoogleFlowGenerationOrchestratorService's three primitives
    (submit/observe/download) across every planned scene, using
    prompts from job.cinematic_prompt_package - the "queue/worker
    loop" that class's own docstring says a caller must build, and
    which nothing in this codebase built before this.

    Deliberately operator-triggered only (never called from
    ContentIntelligencePipeline.run_all()), given this session's own
    proven Google Flow flakiness: false SUBMISSION_UNCERTAIN negatives
    (a real generation succeeding despite the code reporting failure),
    silent download failures, and duration values Flow silently
    rejects. A scene sitting at SUBMISSION_UNCERTAIN or any other
    interrupt state is never auto-retried here - that state means
    "call the operator," not "resubmit automatically" (GF-7's own real
    reconciliation needs the live adapter to check, which this service
    does not attempt).

    No semantic/multimodal QC exists in this codebase (a disclosed
    gap, not fabricated) - per explicit instruction, a downloaded clip
    that passes technical validation (ffprobe-based: readable, has a
    video stream, real duration/dimensions) is promoted straight to
    READY without a visual continuity check. A human reviews the
    actual footage separately.
    """

    def __init__(
        self,
        *,
        orchestrator: GoogleFlowGenerationOrchestratorService,
        asset_workflow_service: SceneAssetWorkflowService,
        video_clip_builder_service: SceneAssetVideoClipBuilderService | None = None,
        poll_interval_seconds: float = 15.0,
        max_poll_attempts: int = 40,
        sleep_fn: Callable[[float], None] = time.sleep,
        estimated_cost_usd_per_scene: float = 0.0,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("Poll interval must be positive.")

        if max_poll_attempts < 1:
            raise ValueError("Max poll attempts must be at least 1.")

        self._orchestrator = orchestrator
        self._asset_workflow_service = asset_workflow_service
        self._video_clip_builder_service = (
            video_clip_builder_service or SceneAssetVideoClipBuilderService()
        )
        self._poll_interval_seconds = poll_interval_seconds
        self._max_poll_attempts = max_poll_attempts
        self._sleep_fn = sleep_fn
        self._estimated_cost_usd_per_scene = estimated_cost_usd_per_scene

    def generate_all(self, job: VideoJob) -> SceneCompletenessReport:
        for scene in sorted(job.scenes, key=lambda scene: scene.scene_number):
            self.generate_one(job, scene.scene_number)

        return SceneCompletenessService().check(job)

    def generate_one(self, job: VideoJob, scene_number: int) -> SceneCompletenessEntry:
        scene = next(
            (s for s in job.scenes if s.scene_number == scene_number),
            None,
        )

        if scene is None:
            raise ValueError(f"Job has no scene numbered {scene_number}.")

        attempt = GoogleFlowGenerationLedgerService.latest_attempt_for_scene(
            job, scene_number
        )

        if attempt is None:
            attempt = self._submit(job, scene)
        elif attempt.state in _POLLABLE_STATES:
            attempt = self._poll_until_settled(job, attempt)

        if attempt.state == GoogleFlowGenerationState.READY_TO_DOWNLOAD:
            attempt = self._orchestrator.download_attempt(job, attempt)

        if attempt.state == GoogleFlowGenerationState.DOWNLOADED:
            attempt = self._orchestrator.validate_downloaded_attempt(job, attempt)
            GoogleFlowGenerationLedgerService.replace_attempt(job, attempt)

        if attempt.state == GoogleFlowGenerationState.DOWNLOADED:
            # validate_downloaded_attempt() only ever leaves an attempt
            # at DOWNLOADED when technical validation passed (a
            # failing one transitions straight to QC_FAILED) - no
            # semantic/multimodal QC exists in this codebase (a
            # disclosed gap), so a technically-valid download is
            # promoted directly to READY per explicit instruction to
            # skip visual QC; a human reviews the footage separately.
            attempt = attempt.with_transition(
                GoogleFlowGenerationState.READY,
                detail=(
                    "Promoted directly to READY: technical validation "
                    "passed and no semantic/multimodal QC is built in "
                    "this codebase. Skipped per explicit instruction; "
                    "review the footage manually."
                ),
            )
            GoogleFlowGenerationLedgerService.replace_attempt(job, attempt)

        if attempt.state == GoogleFlowGenerationState.READY:
            self._attach(job, scene, attempt)

        report = SceneCompletenessService().check(job)

        return next(
            entry for entry in report.entries if entry.scene_number == scene_number
        )

    def _submit(self, job: VideoJob, scene: Scene) -> GoogleFlowGenerationAttempt:
        prompt = ScenePromptExportService._resolve_prompt_text(
            scene, job.cinematic_prompt_package
        )
        duration_seconds = self._clamp_to_verified_duration(
            scene.estimated_duration_seconds
        )

        attempt = self._orchestrator.submit_new_attempt(
            job,
            scene_number=scene.scene_number,
            prompt=prompt,
            prompt_version=_PROMPT_VERSION,
            idempotency_key=str(uuid.uuid4()),
            execution_settings=GoogleFlowExecutionSettings(
                duration_seconds=float(duration_seconds)
            ),
            locked_script_hash=(
                job.script_lock.script_content_hash
                if job.script_lock is not None
                else None
            ),
            estimated_cost_usd=self._estimated_cost_usd_per_scene,
        )

        if attempt.state in _POLLABLE_STATES:
            attempt = self._poll_until_settled(job, attempt)

        return attempt

    def _poll_until_settled(
        self, job: VideoJob, attempt: GoogleFlowGenerationAttempt
    ) -> GoogleFlowGenerationAttempt:
        remaining = self._max_poll_attempts

        while attempt.state in _POLLABLE_STATES and remaining > 0:
            self._sleep_fn(self._poll_interval_seconds)
            attempt = self._orchestrator.observe_attempt(job, attempt)
            remaining -= 1

        return attempt

    def _attach(
        self,
        job: VideoJob,
        scene: Scene,
        attempt: GoogleFlowGenerationAttempt,
    ) -> None:
        existing_state = next(
            (
                state
                for state in job.scene_asset_states
                if state.scene_number == scene.scene_number
            ),
            None,
        )
        state = existing_state or SceneAssetState(
            scene_id=str(scene.id), scene_number=scene.scene_number
        )

        real_duration = (
            attempt.technical_validation.duration_seconds
            if attempt.technical_validation is not None
            else None
        )

        updated_state = self._asset_workflow_service.apply_decision(
            scene=scene,
            state=state,
            decision=AssetUserDecision.AI_GENERATE,
            ai_generated_file_path=attempt.downloaded_file,
            ai_generated_duration_seconds=(
                real_duration
                if real_duration is not None
                else float(scene.estimated_duration_seconds)
            ),
        )

        if existing_state is None:
            job.scene_asset_states.append(updated_state)
        else:
            index = job.scene_asset_states.index(existing_state)
            job.scene_asset_states[index] = updated_state

        job.video_clips = self._video_clip_builder_service.build_clips(
            scenes=job.scenes,
            states=job.scene_asset_states,
        )

    @staticmethod
    def _clamp_to_verified_duration(requested_seconds: int) -> int:
        """
        Real-world finding this session: Google Flow only accepts a
        fixed set of durations (4/6/8/10s) - requesting anything else
        (e.g. 12s) fails with FLOW_SETTINGS_UNAVAILABLE. Clamp to the
        closest verified value rather than passing the raw estimate
        straight through and letting the submission fail.
        """

        return min(
            VERIFIED_DURATIONS_SECONDS,
            key=lambda verified: abs(verified - requested_seconds),
        )
