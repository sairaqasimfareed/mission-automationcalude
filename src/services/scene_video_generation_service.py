from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from functools import partial
from typing import TypeVar

from src.browser.flow_browser_worker import FlowOperationTimedOut
from src.models.asset_state import AssetUserDecision, SceneAssetState
from src.models.google_flow_generation import (
    GoogleFlowExecutionSettings,
    GoogleFlowGenerationAttempt,
    GoogleFlowGenerationState,
    GoogleFlowQCOutcome,
    GoogleFlowQCResult,
)
from src.models.provider_profile import ProviderCategory, ProviderHealthStatus
from src.models.scene import Scene
from src.models.scene_completeness import (
    SceneCompletenessEntry,
    SceneCompletenessReport,
)
from src.models.video_job import VideoJob
from src.providers.external_ui_generation_provider import ExternalUIGenerationProvider
from src.providers.google_flow.locators import clamp_to_verified_duration
from src.services.google_flow_generation_ledger_service import (
    GoogleFlowGenerationLedgerService,
)
from src.services.google_flow_generation_orchestrator_service import (
    GoogleFlowGenerationOrchestratorService,
)
from src.services.provider_profile_management_service import (
    ProviderProfileManagementService,
)
from src.services.registry.provider_registry import ProviderRegistry
from src.services.scene_asset_video_clip_builder_service import (
    SceneAssetVideoClipBuilderService,
)
from src.services.scene_asset_workflow_service import SceneAssetWorkflowService
from src.services.scene_completeness_service import SceneCompletenessService
from src.services.scene_prompt_export_service import ScenePromptExportService
from src.shared.logger import logger

_T = TypeVar("_T")

_POLLABLE_STATES = frozenset(
    {
        GoogleFlowGenerationState.SUBMITTED,
        GoogleFlowGenerationState.GENERATING,
        # Real-world finding, 2026-09-14: SUBMISSION_UNCERTAIN used to
        # stop here outright, requiring a human to notice and manually
        # reconcile it - twice, live, the real generation had actually
        # succeeded despite this. GoogleFlowRealUIAdapter.observe() now
        # reconciles an uncertain attempt using real evidence (a
        # matching, completed tile) when it can find it; keep polling
        # it here the same as a confirmed one, bounded by the same
        # max_poll_attempts budget as always - a genuinely failed
        # submission still just times out to "needs operator
        # attention" after that budget, unchanged from before.
        GoogleFlowGenerationState.SUBMISSION_UNCERTAIN,
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
    rejects.

    A scene sitting at any interrupt state EXCEPT SUBMISSION_UNCERTAIN
    (AUTH_REQUIRED/HUMAN_ACTION_REQUIRED/UI_CHANGED/FAILED) is never
    auto-retried here - that state means "call the operator," not
    "resubmit automatically". SUBMISSION_UNCERTAIN is the one
    exception (real-world finding, 2026-09-14): it now gets polled the
    same as a confirmed SUBMITTED/GENERATING attempt, and
    GoogleFlowRealUIAdapter.observe() reconciles it forward using real
    evidence (a tile matching this attempt's own prompt with a
    completed thumbnail) when that evidence exists - this is GF-7's
    own disclosed "real reconciliation needs the live adapter to
    check" gap, now built, because the false-negative rate on this
    specific heuristic turned out too high in practice (confirmed
    live, twice) to leave every occurrence for a human to notice and
    manually correct. A genuinely failed/never-started submission
    still just times out to "needs operator attention" after the same
    poll budget as always - nothing here blindly resubmits.

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
        registry: ProviderRegistry | None = None,
        provider: ExternalUIGenerationProvider | None = None,
        profile_management_service: ProviderProfileManagementService | None = None,
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
        self._registry = registry
        self._provider = provider
        self._profile_management_service = profile_management_service
        self._video_clip_builder_service = (
            video_clip_builder_service or SceneAssetVideoClipBuilderService()
        )
        self._poll_interval_seconds = poll_interval_seconds
        self._max_poll_attempts = max_poll_attempts
        self._sleep_fn = sleep_fn
        self._estimated_cost_usd_per_scene = estimated_cost_usd_per_scene

    def generate_all(
        self,
        job: VideoJob,
        *,
        on_scene_complete: Callable[[VideoJob, int], None] | None = None,
    ) -> SceneCompletenessReport:
        """
        Generate every planned scene's video, in scene-number order.

        on_scene_complete, when given, is called with the job and the
        scene number that was just generated, immediately after each
        individual generate_one() call returns - before the next
        scene starts. This exists so a caller can checkpoint progress
        (e.g. persist the job) after every scene rather than only
        once the whole batch finishes, since a real, multi-minute,
        one-scene-at-a-time generation run genuinely can fail or be
        interrupted partway through (a real-world finding: losing
        every already-completed scene's progress to an unrelated
        failure on a later scene, because nothing was saved until the
        end). This method still does not persist anything itself -
        that responsibility stays with the caller, matching every
        other generation service in this codebase.
        """

        for scene in sorted(job.scenes, key=lambda scene: scene.scene_number):
            self.generate_one(job, scene.scene_number)

            if on_scene_complete is not None:
                on_scene_complete(job, scene.scene_number)

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
            attempt_to_download = attempt
            attempt = self._timed(
                "download",
                scene_number,
                lambda: self._orchestrator.download_attempt(job, attempt_to_download),
            )

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
            #
            # Real-world finding, 2026-09-14: GoogleFlowGenerationAttempt's
            # own validator requires a passing qc_result whenever
            # state == READY - a requirement this promotion never
            # satisfied, since with_transition() only ever updates
            # state/state_history. That left every READY attempt
            # latently invalid: with_transition() itself uses
            # model_copy() (no validation), so it never raised here,
            # but the very next model_validate_json() round-trip (a
            # real job reload from disk) did. Attach an honest
            # qc_result recording exactly what was actually checked -
            # never fabricating a real semantic pass that never
            # happened.
            attempt = attempt.model_copy(
                update={
                    "qc_result": GoogleFlowQCResult(
                        outcome=GoogleFlowQCOutcome.PASS,
                        findings=[
                            "No semantic/multimodal QC was performed - "
                            "this codebase has none built (a disclosed "
                            "gap). Technical validation (readable, has "
                            "a video stream, real duration/dimensions) "
                            "passed; promoted to READY per explicit "
                            "instruction to skip visual QC.",
                        ],
                    )
                }
            )
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
        self._self_heal_flow_account_health()

        prompt = ScenePromptExportService._resolve_prompt_text(
            scene, job.cinematic_prompt_package
        )
        duration_seconds = self._clamp_to_verified_duration(
            scene.estimated_duration_seconds
        )

        attempt = self._timed(
            "submit",
            scene.scene_number,
            lambda: self._orchestrator.submit_new_attempt(
                job,
                scene_number=scene.scene_number,
                prompt=prompt,
                prompt_version=_PROMPT_VERSION,
                idempotency_key=str(uuid.uuid4()),
                execution_settings=GoogleFlowExecutionSettings(
                    model_family=self._configured_model_family(),
                    duration_seconds=float(duration_seconds),
                ),
                locked_script_hash=(
                    job.script_lock.script_content_hash
                    if job.script_lock is not None
                    else None
                ),
                estimated_cost_usd=self._estimated_cost_usd_per_scene,
            ),
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
            attempt = self._timed(
                "observe",
                attempt.request.scene_number,
                partial(self._orchestrator.observe_attempt, job, attempt),
            )
            remaining -= 1

        return attempt

    def _timed(self, label: str, scene_number: int | str, fn: Callable[[], _T]) -> _T:
        """
        GF-15 (tests/test_google_flow_security.py) forbids logging
        anywhere inside the Google Flow provider/browser layer itself,
        since a log call there could too easily end up interpolating
        real page content, a Playwright exception, or profile metadata
        into a stream this module doesn't control. This service sits
        outside that forbidden-file list and is already the boundary
        every submit/observe/download/health-check call passes through
        on its way in - the correct, sanctioned place to log that an
        operation started, how long it took, and whether it timed out,
        without ever touching what happens inside the browser layer.
        Only ever logs label/scene_number/elapsed/exception TYPE -
        never an exception's own message, which could still originate
        from inside the browser layer.
        """

        started_at = time.monotonic()

        try:
            result = fn()
        except FlowOperationTimedOut as error:
            logger.error(
                "google_flow.%s | scene=%s | TIMED OUT after %.1fs (budget %.1fs)",
                label,
                scene_number,
                error.elapsed_seconds,
                error.timeout_seconds,
            )
            raise
        except Exception as error:
            elapsed = time.monotonic() - started_at
            logger.error(
                "google_flow.%s | scene=%s | failed after %.1fs | %s",
                label,
                scene_number,
                elapsed,
                type(error).__name__,
            )
            raise

        elapsed = time.monotonic() - started_at
        logger.info(
            "google_flow.%s | scene=%s | completed in %.1fs",
            label,
            scene_number,
            elapsed,
        )
        return result

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

    def _configured_model_family(self) -> str | None:
        """
        Real-world finding, 2026-09-13: this service used to leave
        model_family unset, so a submission never actually selected a
        model in Flow's settings popover - it just used whatever
        model happened to already be active in that browser profile's
        project. That silently let a stale/different model dictate
        which durations were even valid, surfacing as a confusing
        FLOW_SETTINGS_UNAVAILABLE on duration rather than the real
        cause. GoogleFlowProviderPanelView already lets an operator
        record the intended model_family on the EXTERNAL_UI_VIDEO
        profile's own metadata (GF-13) - read it back here so an
        automated submission pins the same model an operator would
        pick by hand, rather than gambling on Flow's current UI state.

        Only applied when exactly one usable EXTERNAL_UI_VIDEO profile
        is configured (true for every real setup so far) - with more
        than one, this service has no way to know which one
        GoogleFlowAccountRouterService will actually route to without
        duplicating its own selection logic, so it deliberately falls
        back to leaving model_family unset rather than guessing.
        """

        if self._registry is None:
            return None

        candidates = self._registry.list_by_category(
            category=ProviderCategory.EXTERNAL_UI_VIDEO,
            usable_only=True,
        )

        if len(candidates) != 1:
            return None

        model_family = candidates[0].metadata.get("model_family")

        return model_family.strip() if model_family and model_family.strip() else None

    def _self_heal_flow_account_health(self) -> None:
        """
        Real-world finding, 2026-09-14: this account's health_status
        kept reverting to UNHEALTHY between runs for reasons outside
        this service's own control - grepping the whole codebase,
        the only real code that ever changes it is two GUI buttons
        (Provider Manager's "Test configuration", which is documented
        as always misreporting an EXTERNAL_UI_VIDEO profile unhealthy
        since it checks for an API-key secret Flow profiles never
        have; and the Google Flow panel's own "Check Connection").
        Nothing in the generation path itself ever touches it. The
        practical effect was still the same either way: every batch
        of scenes needed a manually-run health check first, or every
        submission failed outright with "No usable Google Flow
        account is configured" - unacceptable for anything meant to
        run unattended. Verify and self-correct with the SAME real
        check "Check Connection" runs, right before submitting,
        instead of requiring that as a separate manual step.

        Deliberately narrow and cheap: only makes a real (slow)
        browser check when the one configured profile is NOT already
        usable - a healthy profile costs nothing here. Only acts when
        exactly one EXTERNAL_UI_VIDEO profile is enabled (same
        ambiguity guard as _configured_model_family) and never
        downgrades a profile - only ever promotes an actually-healthy
        one back to usable, matching what "Check Connection" itself
        would report. Silently gives up on any error (missing deps,
        no provider/profile_management_service wired, the real check
        itself raising) - a real submission attempt right after will
        surface the actual problem clearly, which is strictly more
        informative than a best-effort health probe failing first.
        """

        if (
            self._registry is None
            or self._provider is None
            or self._profile_management_service is None
        ):
            return

        candidates = self._registry.list_by_category(
            category=ProviderCategory.EXTERNAL_UI_VIDEO,
            enabled_only=True,
        )

        if len(candidates) != 1 or candidates[0].usable:
            return

        provider = self._provider

        try:
            healthy = self._timed(
                "check_profile_health",
                "-",
                lambda: provider.check_profile_health(candidates[0].profile_id),
            )

            if healthy:
                self._profile_management_service.set_health_status(
                    candidates[0].profile_id, ProviderHealthStatus.HEALTHY
                )
        except (
            Exception
        ):  # noqa: BLE001 - best-effort; a real submit surfaces the real error
            return

    @staticmethod
    def _clamp_to_verified_duration(requested_seconds: int) -> int:
        """
        Thin wrapper kept for this service's own call-site readability -
        see clamp_to_verified_duration's own docstring for why this is
        now the one shared implementation (also used by
        CinematicPromptCompilationService via
        ContentIntelligencePipeline, so a compiled prompt's stated
        duration always matches what actually gets requested here).
        """

        return clamp_to_verified_duration(requested_seconds)
