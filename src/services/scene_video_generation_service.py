from __future__ import annotations

import hashlib
import re
import tempfile
import time
import uuid
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import TypeVar

from src.browser.flow_browser_worker import FlowOperationTimedOut
from src.models.asset_state import AssetCandidate, AssetUserDecision, SceneAssetState
from src.models.google_flow_generation import (
    GoogleFlowExecutionSettings,
    GoogleFlowGenerationAttempt,
    GoogleFlowGenerationState,
    GoogleFlowQCOutcome,
    GoogleFlowQCResult,
    GoogleFlowReferenceAsset,
    GoogleFlowReferenceRole,
)
from src.models.media_strategy import SceneSourceType
from src.models.provider_profile import ProviderCategory, ProviderHealthStatus
from src.models.scene import Scene
from src.models.scene_completeness import (
    SceneCompletenessEntry,
    SceneCompletenessReport,
)
from src.models.video_job import VideoJob
from src.models.visual_continuity import CanonicalEntityType
from src.providers.external_ui_generation_provider import ExternalUIGenerationProvider
from src.providers.google_flow.locators import (
    VERIFIED_DURATIONS_SECONDS,
    clamp_to_verified_duration,
)
from src.services.asset_storage_service import AssetStorageService
from src.services.frame_extraction_service import FrameExtractionService
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
from src.services.scene_clip_split_planning_service import (
    SceneClipSplitPlanningService,
)
from src.services.scene_completeness_service import SceneCompletenessService
from src.services.scene_prompt_export_service import ScenePromptExportService
from src.shared.logger import logger

_T = TypeVar("_T")

# Matches CinematicPromptCompilationService._compile_one's own exact
# "Duration: Ns seconds." text (f"Duration: {duration:.0f} seconds.") -
# kept as the single source of truth for that literal format so a
# real submission can re-patch it with the real, final duration this
# scene is about to request. See _submit()'s own real-world-finding
# comment for why this re-patch exists.
_DURATION_STATEMENT_PATTERN = re.compile(r"Duration: \d+ seconds\.")

# Matches CinematicPromptCompilationService._render_shot_progression's
# own exact "[X-Ys]" beat range text
# (f"[{start:g}-{end:g}s]") - used to find the LAST beat's own
# rendered end time so it can be extended to the real final duration.
_SHOT_PROGRESSION_BEAT_PATTERN = re.compile(r"\[([\d.]+)-([\d.]+)s\]")


def _extend_last_beat_to_real_duration(prompt: str, real_duration: float) -> str:
    """
    Extend a compiled prompt's LAST "Shot progression" beat range to
    end at the real final duration, if it currently ends earlier - see
    _submit()'s own real-world-finding comment for why. A no-op when
    the prompt has no beat ranges at all, or the last one already
    reaches (or exceeds) real_duration.
    """

    matches = list(_SHOT_PROGRESSION_BEAT_PATTERN.finditer(prompt))

    if not matches:
        return prompt

    last_match = matches[-1]

    current_end = float(last_match.group(2))

    if current_end >= real_duration:
        return prompt

    start_text = last_match.group(1)

    replacement = f"[{start_text}-{real_duration:g}s]"

    return prompt[: last_match.start()] + replacement + prompt[last_match.end() :]


# Real-world finding, 2026-09-21 (Phase 3/4's own real verification):
# Google Flow refuses image ingredients outright below its max
# verified duration ("You cannot use image ingredients with the
# currently selected duration" - confirmed directly on 4s and 6s,
# both rejected; 8s accepted) - confirmed live by the account owner
# watching the browser. A scene that has a real reference to attach
# (see _resolve_reference_assets) must therefore always request the
# max verified duration, regardless of what its real narration would
# otherwise clamp to - the same "rounding up can't itself cause an
# overshoot" reasoning clamp_to_verified_duration's own docstring
# already established, just applied unconditionally here rather than
# only when narration happens to need it. The alternative (silently
# falling back to text-only continuity for a <8s scene) would quietly
# weaken continuity exactly where it is least visible - never done.
_MINIMUM_DURATION_SECONDS_FOR_REFERENCE_ASSETS = max(VERIFIED_DURATIONS_SECONDS)


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
        frame_extraction_service: FrameExtractionService | None = None,
        asset_storage_service: AssetStorageService | None = None,
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
        # Optional: visual-continuity self-consistency (see
        # _extract_reference_for_new_identities). Without both, this
        # service reproduces its exact prior behavior - no frame
        # extraction, no reference population.
        self._frame_extraction_service = frame_extraction_service
        self._asset_storage_service = asset_storage_service

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

        # Phase 5 (multi-clip scene splitting): a scene whose real
        # narration exceeds Flow's own max single-clip duration is
        # generated as several consecutive sub-clips instead - a
        # scene with no real narration duration yet always takes the
        # single-clip path below (matching this class's own existing
        # "fall back to the estimate" behavior for that case), only
        # ever reconsidering the split question once real data exists.
        if (
            scene.real_narration_duration_seconds is not None
            and SceneClipSplitPlanningService.needs_split(
                scene.real_narration_duration_seconds
            )
        ):
            return self._generate_split_scene(job, scene)

        attempt = self._drive_to_terminal(job, scene)

        if attempt.state == GoogleFlowGenerationState.READY:
            self._attach(job, scene, attempt)

            self._extract_reference_for_new_identities(job, scene)

        report = SceneCompletenessService().check(job)

        return next(
            entry for entry in report.entries if entry.scene_number == scene_number
        )

    def _drive_to_terminal(
        self,
        job: VideoJob,
        scene: Scene,
        *,
        clip_sequence_index: int = 0,
        duration_override: float | None = None,
        extra_reference_assets: list[GoogleFlowReferenceAsset] | None = None,
    ) -> GoogleFlowGenerationAttempt:
        """
        Drive one (scene_number, clip_sequence_index) sub-clip's real
        Google Flow attempt from wherever it currently sits through to
        a terminal state: submit (or resume polling an existing
        in-flight attempt), download once ready, technically validate,
        and promote to READY when validation passes.

        This is generate_one()'s own single-clip logic, unchanged in
        behavior, factored out so Phase 5's multi-clip sub-clip loop
        (_generate_split_scene) drives every sub-clip's attempt
        through the exact same, already-proven state machine rather
        than a second, parallel implementation.
        """

        attempt = GoogleFlowGenerationLedgerService.latest_attempt_for_scene(
            job, scene.scene_number, clip_sequence_index=clip_sequence_index
        )

        if attempt is None:
            attempt = self._submit(
                job,
                scene,
                clip_sequence_index=clip_sequence_index,
                duration_override=duration_override,
                extra_reference_assets=extra_reference_assets,
            )
        elif attempt.state in _POLLABLE_STATES:
            attempt = self._poll_until_settled(job, attempt)

        if attempt.state == GoogleFlowGenerationState.READY_TO_DOWNLOAD:
            attempt_to_download = attempt
            attempt = self._timed(
                "download",
                scene.scene_number,
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

        return attempt

    def _generate_split_scene(
        self, job: VideoJob, scene: Scene
    ) -> SceneCompletenessEntry:
        """
        Phase 5: a scene whose real narration exceeds Google Flow's
        single-clip max is generated as several consecutive same-
        prompt sub-clips instead of being destructively trimmed - the
        same real bug class Phase 1's audio-first work already fixed
        for the single-clip case, extended here to narration long
        enough that even the max verified duration (8s) genuinely
        isn't room enough.

        Sub-clips are generated strictly in order: sub-clip N's own
        real last frame becomes sub-clip N+1's FIRST_FRAME reference
        (the same frame-extraction/storage machinery Phase 2 built for
        cross-scene self-consistency, reused here for intra-scene seam
        continuity). A sub-clip that doesn't reach READY stops the
        whole scene here, matching this class's own "interrupt state
        means call the operator, never auto-retry" rule -
        already-succeeded sub-clips are simply not attached yet; the
        next generate_one() call resumes exactly where this left off,
        since every sub-clip's own attempt is independently tracked in
        the ledger by (scene_number, clip_sequence_index).
        """

        real_duration = scene.real_narration_duration_seconds
        assert real_duration is not None  # narrowed by generate_one()'s own check

        durations = SceneClipSplitPlanningService.plan(real_duration)

        successful_attempts: list[GoogleFlowGenerationAttempt] = []
        seam_reference_path: str | None = None

        for index, duration in enumerate(durations):
            extra_references: list[GoogleFlowReferenceAsset] = []

            if seam_reference_path is not None:
                seam_reference = self._build_seam_reference_asset(seam_reference_path)

                if seam_reference is not None:
                    extra_references.append(seam_reference)

            attempt = self._drive_to_terminal(
                job,
                scene,
                clip_sequence_index=index,
                duration_override=duration,
                extra_reference_assets=extra_references,
            )

            if attempt.state != GoogleFlowGenerationState.READY:
                break

            successful_attempts.append(attempt)

            is_last_sub_clip = index + 1 >= len(durations)

            if not is_last_sub_clip:
                seam_reference_path = self._extract_seam_reference(job, scene, attempt)

        if len(successful_attempts) == len(durations):
            self._attach_split_scene(job, scene, successful_attempts)

            self._extract_reference_for_new_identities(job, scene)

        report = SceneCompletenessService().check(job)

        return next(
            entry
            for entry in report.entries
            if entry.scene_number == scene.scene_number
        )

    def _build_seam_reference_asset(
        self, source_path: str
    ) -> GoogleFlowReferenceAsset | None:
        """Best-effort, matching this class's established resilience
        pattern: a missing/unreadable seam-reference file just means
        the next sub-clip submits without it (a visible continuity
        gap, not a correctness failure) rather than blocking the
        scene."""

        path = Path(source_path)

        if not path.exists():
            logger.warning("Seam reference file no longer exists: %s", source_path)

            return None

        checksum = hashlib.sha256(path.read_bytes()).hexdigest()

        return GoogleFlowReferenceAsset(
            source_path=str(path),
            checksum=checksum,
            role=GoogleFlowReferenceRole.FIRST_FRAME,
        )

    def _extract_seam_reference(
        self,
        job: VideoJob,
        scene: Scene,
        attempt: GoogleFlowGenerationAttempt,
    ) -> str | None:
        """
        Extract sub-clip N's real last frame for sub-clip N+1's own
        FIRST_FRAME reference - the intra-scene counterpart to
        _extract_reference_for_new_identities' cross-scene extraction,
        reusing the exact same frame-extraction/storage primitives.
        Best-effort throughout, same reasoning as that method's own
        docstring: a failure here is a continuity enhancement lost,
        never a reason to fail this scene's own generation.
        """

        if (
            self._frame_extraction_service is None
            or self._asset_storage_service is None
        ):
            return None

        if attempt.downloaded_file is None or attempt.technical_validation is None:
            return None

        real_duration = attempt.technical_validation.duration_seconds

        if real_duration is None or real_duration <= 0:
            return None

        try:
            with tempfile.TemporaryDirectory() as temp_directory:
                staged_frame_path = (
                    f"{temp_directory}/scene_{scene.scene_number:03d}_seq_"
                    f"{attempt.request.clip_sequence_index:02d}_last_frame.jpg"
                )

                extracted_path = self._frame_extraction_service.extract_last_frame(
                    video_path=attempt.downloaded_file,
                    video_duration_seconds=float(real_duration),
                    output_path=staged_frame_path,
                )

                result = self._asset_storage_service.store_extracted_frame(
                    source_path=extracted_path,
                    project_id=str(job.id),
                    scene_number=scene.scene_number,
                    title=(
                        f"Seam reference - scene {scene.scene_number} "
                        f"sub-clip {attempt.request.clip_sequence_index}"
                    ),
                )
        except Exception as error:
            logger.warning(
                "Seam-reference frame extraction failed for scene %s "
                "sub-clip %s: %s",
                scene.scene_number,
                attempt.request.clip_sequence_index,
                type(error).__name__,
            )

            return None

        if not result.success or result.asset is None:
            logger.warning(
                "Storing the seam-reference frame failed for scene %s "
                "sub-clip %s: %s",
                scene.scene_number,
                attempt.request.clip_sequence_index,
                result.message,
            )

            return None

        return result.asset.file_path

    def _attach_split_scene(
        self,
        job: VideoJob,
        scene: Scene,
        attempts: list[GoogleFlowGenerationAttempt],
    ) -> None:
        """
        Attach every sub-clip's real, downloaded, validated file as
        this scene's video - attempts[0] becomes the primary
        selected_candidate exactly like _attach()'s own single-clip
        path always has, attempts[1:] become
        additional_ai_generated_sub_clips entries (Phase 5's own
        additive extension). SceneAssetVideoClipBuilderService turns
        each into its own VideoClip, one per real sub-clip, sharing
        one scene_number and an incrementing clip_sequence_index.
        """

        primary_attempt = attempts[0]

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

        primary_duration = (
            primary_attempt.technical_validation.duration_seconds
            if primary_attempt.technical_validation is not None
            else None
        )

        updated_state = self._asset_workflow_service.apply_decision(
            scene=scene,
            state=state,
            decision=AssetUserDecision.AI_GENERATE,
            ai_generated_file_path=primary_attempt.downloaded_file,
            ai_generated_duration_seconds=(
                primary_duration
                if primary_duration is not None
                else float(scene.estimated_duration_seconds)
            ),
        )

        sub_clip_candidates: list[AssetCandidate] = []

        for attempt in attempts[1:]:
            duration = (
                attempt.technical_validation.duration_seconds
                if attempt.technical_validation is not None
                else None
            )

            sub_clip_candidates.append(
                AssetCandidate(
                    title=scene.title,
                    source_type=SceneSourceType.AI_GENERATE,
                    file_path=attempt.downloaded_file or "",
                    provider="google_flow",
                    license_type="generated",
                    duration_seconds=(
                        duration
                        if duration is not None
                        else float(scene.estimated_duration_seconds)
                    ),
                    resolution="1920x1080",
                    aspect_ratio="16:9",
                )
            )

        updated_state.additional_ai_generated_sub_clips = sub_clip_candidates

        if existing_state is None:
            job.scene_asset_states.append(updated_state)
        else:
            index = job.scene_asset_states.index(existing_state)
            job.scene_asset_states[index] = updated_state

        job.video_clips = self._video_clip_builder_service.build_clips(
            scenes=job.scenes,
            states=job.scene_asset_states,
        )

    def _submit(
        self,
        job: VideoJob,
        scene: Scene,
        *,
        clip_sequence_index: int = 0,
        duration_override: float | None = None,
        extra_reference_assets: list[GoogleFlowReferenceAsset] | None = None,
    ) -> GoogleFlowGenerationAttempt:
        """
        clip_sequence_index/duration_override/extra_reference_assets
        exist for Phase 5 (multi-clip scene splitting) alone - every
        pre-Phase-5 caller uses the defaults (0/None/None), reproducing
        this method's exact prior behavior. duration_override, when
        given, replaces the normal real-narration-vs-estimate
        computation outright (SceneClipSplitPlanningService has
        already decided this sub-clip's own duration) - but the
        reference-forces-max-duration rule below still applies
        AFTERWARD, unconditionally, on top of whichever base value was
        chosen: every sub-clip after the first always carries a seam
        reference (its predecessor's own last frame, for visual
        continuity across the split), so it always ends up forced to
        the max verified duration regardless of what the split plan
        originally computed for its share - the same real Flow
        constraint (image ingredients refused below the max duration)
        Phase 3/4 already found, just composing naturally here rather
        than needing its own separate rule.
        """

        self._self_heal_flow_account_health()

        prompt = ScenePromptExportService._resolve_prompt_text(
            scene, job.cinematic_prompt_package
        )

        if duration_override is not None:
            target_seconds: float = duration_override
        elif scene.real_narration_duration_seconds is not None:
            # Real-world finding, 2026-09-20: estimated_duration_seconds
            # is a pre-generation word-count guess. VoicePipelineStage
            # now writes scene.real_narration_duration_seconds after
            # this scene's real voice audio is generated and measured -
            # using that instead means the real Google Flow clip is
            # sized from truth, not a guess (the actual root cause of
            # the destructive narration-trimming this replaces).
            target_seconds = scene.real_narration_duration_seconds
        else:
            # Falls back to the old estimate only defensively, for a
            # scene somehow submitted before voice ran - normal
            # operation should never hit it.
            target_seconds = float(scene.estimated_duration_seconds)

            logger.warning(
                "Scene %s was submitted for video generation before its "
                "real narration duration was known; falling back to the "
                "pre-generation estimate.",
                scene.scene_number,
            )

        duration_seconds = self._clamp_to_verified_duration(target_seconds)

        # Phase 4 (real visual continuity): resolve this scene's
        # featured identities' CURRENT self-extracted reference assets
        # fresh, right here - never from job.cinematic_prompt_package's
        # own ResolvedCinematicPrompt.reference_asset_ids, which is
        # compiled once, early, before any scene has generated and so
        # can never contain a reference extracted from an earlier
        # scene in this same job (see _resolve_reference_assets' own
        # docstring). A scene with at least one resolved reference
        # must request the max verified duration - see
        # _MINIMUM_DURATION_SECONDS_FOR_REFERENCE_ASSETS' own comment
        # for why (Flow silently refuses image ingredients below it).
        reference_assets = self._resolve_reference_assets(job, scene) + list(
            extra_reference_assets or []
        )

        if reference_assets:
            duration_seconds = _MINIMUM_DURATION_SECONDS_FOR_REFERENCE_ASSETS

        # Real-world finding, 2026-09-20: confirmed on a real
        # submission (scene 17) - the compiled prompt's own "Duration:
        # Ns seconds." text is baked in far earlier, at Production
        # Plan Phase 4 (CinematicPromptCompilationService), before
        # voice generation has run - so it still states the old,
        # pre-generation estimate even now that duration_seconds above
        # correctly reflects the real narration length. Left
        # unpatched, the prompt TEXT and the real technical
        # duration_seconds parameter disagree (observed directly: text
        # said "6 seconds", the real request correctly asked for 8) -
        # exactly the same class of self-contradiction
        # duration_seconds_resolver was already built to prevent at
        # compile time (see that parameter's own docstring), just
        # reopened here because this real value only exists after
        # compilation already happened. Re-patching the already-
        # compiled text at the one real submission point, using
        # whatever duration_seconds this call is actually about to
        # request, keeps both truthful regardless of which of the two
        # branches above decided it - a harmless no-op in the
        # fallback-to-estimate branch, since that branch's value is
        # exactly what compiled the text in the first place.
        prompt = _DURATION_STATEMENT_PATTERN.sub(
            f"Duration: {duration_seconds:.0f} seconds.",
            prompt,
        )

        # Real-world finding, 2026-09-20: confirmed directly on the
        # same real submission - patching the trailing "Duration: Ns
        # seconds." summary alone was not enough. The compiled
        # "Shot progression: [0-4s] ...; [4-6s] ..." beats
        # (CinematicPromptCompilationService._render_shot_progression)
        # are ALSO baked in at the same earlier, pre-voice compilation
        # time, clamped to the OLD estimate - when the real duration
        # is LONGER (video now follows real narration, which can
        # legitimately need more room than planned), the beats simply
        # stop short, leaving the extra time completely undescribed
        # (observed directly: beats covered 0-4s and 4-6s while the
        # real clip was now 8s, with nothing describing seconds 6-8 at
        # all). That function's own docstring only ever defended
        # against duration SHRINKING (a beat describing action past
        # the real end); growing past the last beat is the new,
        # opposite case this fix introduces. Extending the LAST beat's
        # own end time to the real final duration - not inventing new
        # described action - tells the AI generator its last described
        # action simply continues for the real remaining time, closing
        # the gap without contradicting anything earlier in the
        # prompt. A no-op whenever there is no shot-progression segment
        # at all (a legacy/flat-action prompt) or the beats already
        # reached the real duration.
        prompt = _extend_last_beat_to_real_duration(prompt, duration_seconds)

        attempt = self._timed(
            "submit",
            scene.scene_number,
            lambda: self._orchestrator.submit_new_attempt(
                job,
                scene_number=scene.scene_number,
                clip_sequence_index=clip_sequence_index,
                prompt=prompt,
                prompt_version=_PROMPT_VERSION,
                idempotency_key=str(uuid.uuid4()),
                execution_settings=GoogleFlowExecutionSettings(
                    model_family=self._configured_model_family(),
                    duration_seconds=float(duration_seconds),
                ),
                reference_assets=reference_assets,
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

    def _extract_reference_for_new_identities(
        self,
        job: VideoJob,
        scene: Scene,
    ) -> None:
        """
        Visual continuity, self-consistency only (explicit user
        decision: no manual reference upload) - whatever a character
        or environment looks like in the first real clip it appears in
        becomes its reference for every later scene featuring it,
        fully automatically. Runs right after _attach(), once this
        scene's real clip is in job.video_clips.

        Best-effort throughout: this is a continuity enhancement, not
        a correctness requirement - any failure here is logged and
        this scene's own generation is otherwise unaffected, matching
        this class's established resilience pattern elsewhere (e.g.
        _self_heal_flow_account_health).
        """

        if (
            self._frame_extraction_service is None
            or self._asset_storage_service is None
        ):
            return

        bible = job.visual_continuity_bible

        if bible is None:
            return

        entry = bible.entry_for_scene(scene.scene_number)

        if entry is None or not entry.entity_names:
            return

        # Only identities this scene features AND that have no
        # reference yet at all - i.e. this is their first appearance
        # in the job. An identity that already has one is left alone;
        # later scenes just keep reusing it.
        new_identities = [
            identity
            for identity in bible.identities
            if identity.name in entry.entity_names and not identity.reference_asset_ids
        ]

        if not new_identities:
            return

        # Phase 5 (multi-clip scene splitting): a split scene has
        # several clips sharing this scene_number - the LAST one
        # (highest clip_sequence_index) is the real end of the scene,
        # the correct frame to represent this identity's current look
        # going forward. A no-op change for every non-split scene,
        # which only ever has one matching clip anyway.
        scene_clips = [
            c for c in job.video_clips if c.scene_number == scene.scene_number
        ]
        clip = (
            max(scene_clips, key=lambda c: c.clip_sequence_index)
            if scene_clips
            else None
        )

        if clip is None or clip.local_file is None or clip.duration_seconds <= 0:
            return

        try:
            with tempfile.TemporaryDirectory() as temp_directory:
                staged_frame_path = (
                    f"{temp_directory}/scene_{scene.scene_number:03d}_last_frame.jpg"
                )

                extracted_path = self._frame_extraction_service.extract_last_frame(
                    video_path=clip.local_file,
                    video_duration_seconds=float(clip.duration_seconds),
                    output_path=staged_frame_path,
                )

                result = self._asset_storage_service.store_extracted_frame(
                    source_path=extracted_path,
                    project_id=str(job.id),
                    scene_number=scene.scene_number,
                    title=f"Reference - scene {scene.scene_number}",
                )
        except Exception as error:
            logger.warning(
                "Reference frame extraction failed for scene %s: %s",
                scene.scene_number,
                type(error).__name__,
            )

            return

        if not result.success or result.asset is None:
            logger.warning(
                "Storing the extracted reference frame failed for scene %s: %s",
                scene.scene_number,
                result.message,
            )

            return

        for identity in new_identities:
            identity.reference_asset_ids.append(str(result.asset.id))

    def _resolve_reference_assets(
        self, job: VideoJob, scene: Scene
    ) -> list[GoogleFlowReferenceAsset]:
        """
        Phase 4 (real visual continuity): resolve this scene's
        featured identities' CURRENT reference_asset_ids, fresh, right
        now - never from job.cinematic_prompt_package's own
        ResolvedCinematicPrompt.reference_asset_ids. That field is
        compiled once, early (Production Plan Phase 4), before any
        scene has actually generated - it can never contain a
        self-extracted reference from an earlier scene in this same
        job, since that frame doesn't exist yet at compile time. This
        method runs instead at the one moment that field's staleness
        doesn't matter: _submit() runs at the real, current point in
        generate_all()'s strictly sequential, one-scene-at-a-time loop,
        after every earlier scene's own _extract_reference_for_new_identities
        call has already had its chance to populate references.

        Best-effort, matching this class's established resilience
        pattern: a dangling/missing asset id (deleted file, stale
        index) is logged and skipped for that one identity rather than
        failing the whole scene - this is a continuity enhancement,
        not a correctness requirement. Returns [] whenever there is
        nothing to attach (no asset-storage service wired, no bible,
        no entry for this scene, or no featured identity has a
        reference yet - e.g. every identity's own first appearance).
        """

        if self._asset_storage_service is None:
            return []

        bible = job.visual_continuity_bible

        if bible is None:
            return []

        entry = bible.entry_for_scene(scene.scene_number)

        if entry is None or not entry.entity_names:
            return []

        featured_identities = [
            identity
            for identity in bible.identities
            if identity.name in entry.entity_names and identity.reference_asset_ids
        ]

        resolved: list[GoogleFlowReferenceAsset] = []

        for identity in featured_identities:
            role = (
                GoogleFlowReferenceRole.CHARACTER
                if identity.entity_type == CanonicalEntityType.PERSON
                else GoogleFlowReferenceRole.LOCATION
            )

            for asset_id in identity.reference_asset_ids:
                asset = self._asset_storage_service.asset_index.get(asset_id)

                if asset is None:
                    logger.warning(
                        "Scene %s references identity '%s' asset id %s, "
                        "which no longer resolves in the asset index - "
                        "skipping this reference.",
                        scene.scene_number,
                        identity.name,
                        asset_id,
                    )

                    continue

                asset_path = Path(asset.file_path)

                if not asset_path.exists():
                    logger.warning(
                        "Scene %s references identity '%s' asset %s, whose "
                        "file no longer exists on disk - skipping this "
                        "reference.",
                        scene.scene_number,
                        identity.name,
                        asset_id,
                    )

                    continue

                checksum = (
                    asset.content_hash
                    or hashlib.sha256(asset_path.read_bytes()).hexdigest()
                )

                resolved.append(
                    GoogleFlowReferenceAsset(
                        source_path=str(asset_path),
                        checksum=checksum,
                        role=role,
                    )
                )

        return resolved

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
    def _clamp_to_verified_duration(requested_seconds: float) -> int:
        """
        Thin wrapper kept for this service's own call-site readability -
        see clamp_to_verified_duration's own docstring for why this is
        now the one shared implementation (also used by
        CinematicPromptCompilationService via
        ContentIntelligencePipeline, so a compiled prompt's stated
        duration always matches what actually gets requested here).

        Widened from int to float, 2026-09-20: _submit() now feeds
        this scene.real_narration_duration_seconds when available (a
        real, measured value, not the pre-generation integer guess).
        """

        return clamp_to_verified_duration(requested_seconds)
