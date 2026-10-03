from __future__ import annotations

import hashlib
import tempfile
import time
import uuid
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import TypeVar

from src.browser.flow_browser_worker import FlowOperationTimedOut
from src.models.asset_state import AssetCandidate, AssetUserDecision, SceneAssetState
from src.models.cinematic_prompt import ResolvedCinematicPrompt
from src.models.media_strategy import SceneSourceType
from src.models.muse_generation import (
    MuseGenerationAttempt,
    MuseGenerationState,
    MuseQCOutcome,
    MuseQCResult,
    MuseReferenceAsset,
    MuseReferenceRole,
    is_terminal_state,
)
from src.models.scene import Scene
from src.models.scene_completeness import (
    SceneCompletenessEntry,
    SceneCompletenessStatus,
)
from src.models.video_job import VideoJob
from src.models.video_provider import VideoProvider
from src.models.visual_continuity import CanonicalEntityIdentity, CanonicalEntityType
from src.services.asset_storage_service import AssetStorageService
from src.services.cinematic_prompt_compilation_service import (
    CinematicPromptCompilationService,
)
from src.services.frame_extraction_service import FrameExtractionService
from src.services.muse_generation_ledger_service import MuseGenerationLedgerService
from src.services.muse_generation_orchestrator_service import (
    MuseGenerationOrchestratorService,
)
from src.services.narration_duration_sync_service import (
    sync_real_narration_durations,
)
from src.services.scene_asset_video_clip_builder_service import (
    SceneAssetVideoClipBuilderService,
)
from src.services.scene_asset_workflow_service import SceneAssetWorkflowService
from src.services.scene_clip_split_planning_service import (
    SceneClipSplitPlanningService,
)
from src.services.scene_completeness_service import SceneCompletenessService
from src.services.scene_prompt_export_service import ScenePromptExportService
from src.services.video_provider_rules import (
    MUSE_CLIP_DURATION_SECONDS,
    MUSE_SAFETY_NET_TRIM_TOLERANCE_SECONDS,
    rules_for,
)
from src.shared.logger import logger

_T = TypeVar("_T")

# Confirmed live 2026-09-29: Muse's real UI exposes no duration
# control at all - every generated clip is a fixed ~10 seconds, unlike
# Google Flow's own selectable/clamped duration. No
# MuseExecutionSettings/clamping logic exists to mirror (see
# muse_generation.py's own MuseGenerationRequest docstring) - this is
# simply the one real, fixed value every submission produces.
_MUSE_CLIP_DURATION_SECONDS = MUSE_CLIP_DURATION_SECONDS

# Real-world finding, 2026-09-29: a scene whose real narration is
# shorter than Muse's fixed ~10s clip length used to attach the full,
# untrimmed clip - nothing in the render/timeline pipeline reconciles
# a clip's own duration against the scene's actual narration length
# (TimelineBuilderService trusts VideoClip.duration_seconds as-is;
# DurationMismatchPolicyService only ever recommends a fix, never
# executes one - confirmed by direct investigation of the render
# path). Below this margin, a target duration is treated as "close
# enough to Muse's own fixed length already" - not worth an explicit
# trim instruction or a safety-net correction for a fraction of a
# second nobody would notice.
_SAFETY_NET_TRIM_TOLERANCE_SECONDS = MUSE_SAFETY_NET_TRIM_TOLERANCE_SECONDS

_POLLABLE_STATES = frozenset(
    {
        MuseGenerationState.SUBMITTED,
        MuseGenerationState.GENERATING,
        MuseGenerationState.SUBMISSION_UNCERTAIN,
    }
)

_PROMPT_VERSION = "muse_scene_video_generation_prompt_v1.0.0"


class MuseSceneVideoGenerationService:
    """
    Drives MuseGenerationOrchestratorService's three primitives
    (submit/observe/download) across every planned scene - mirrors
    SceneVideoGenerationService's own core loop, trimmed to Muse's
    real, simpler UI:

    - Phase 5 multi-clip scene splitting (2026-09-29): a scene whose
      real narration exceeds Muse's fixed ~10s single-clip length is
      generated as several consecutive sub-clips instead, mirroring
      Google Flow's own _generate_split_scene exactly - reuses the
      SAME provider-neutral SceneClipSplitPlanningService (parameterized
      for Muse's own 10s ceiling and an identity clamp, since Muse has
      no discrete "verified duration" grid to round up to the way Flow
      does) and the SAME CinematicPromptCompilationService.
      compile_sub_clip_prompts for per-sub-clip prompts.
    - No duration clamping/model-family settings (Muse has no such
      controls to drive - see MuseGenerationRequest's own docstring).
    - No self-heal-account-health pass (a resilience nicety, not core
      functionality - can be added later mirroring Google Flow's own
      _self_heal_flow_account_health if warranted).

    Reuses the EXACT SAME job.visual_continuity_bible/job.
    extracted_frame_asset_index/FrameExtractionService/
    AssetStorageService/SceneAssetWorkflowService/
    SceneAssetVideoClipBuilderService/SceneCompletenessService Google
    Flow's own service uses - these were already provider-agnostic, so
    a reference extracted from a Muse-generated clip is automatically
    available to a later Google-Flow-generated scene featuring the
    same identity, and vice versa. True cross-provider visual
    continuity falls out of this reuse for free, not built specially.
    """

    def __init__(
        self,
        *,
        orchestrator: MuseGenerationOrchestratorService,
        asset_workflow_service: SceneAssetWorkflowService,
        video_clip_builder_service: SceneAssetVideoClipBuilderService | None = None,
        poll_interval_seconds: float = 15.0,
        max_poll_attempts: int = 40,
        sleep_fn: Callable[[float], None] = time.sleep,
        estimated_cost_usd_per_scene: float = 0.0,
        frame_extraction_service: FrameExtractionService | None = None,
        asset_storage_service: AssetStorageService | None = None,
        cinematic_prompt_compilation_service: (
            CinematicPromptCompilationService | None
        ) = None,
        generate_all_settle_seconds: float = 20.0,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("Poll interval must be positive.")

        if max_poll_attempts < 1:
            raise ValueError("Max poll attempts must be at least 1.")

        if generate_all_settle_seconds < 0:
            raise ValueError("Generate-all settle seconds cannot be negative.")

        self._orchestrator = orchestrator
        self._asset_workflow_service = asset_workflow_service
        self._video_clip_builder_service = (
            video_clip_builder_service or SceneAssetVideoClipBuilderService()
        )
        self._poll_interval_seconds = poll_interval_seconds
        self._max_poll_attempts = max_poll_attempts
        self._sleep_fn = sleep_fn
        self._estimated_cost_usd_per_scene = estimated_cost_usd_per_scene
        self._frame_extraction_service = frame_extraction_service
        self._asset_storage_service = asset_storage_service
        self._cinematic_prompt_compilation_service = (
            cinematic_prompt_compilation_service or CinematicPromptCompilationService()
        )
        self._generate_all_settle_seconds = generate_all_settle_seconds

    def generate_one(self, job: VideoJob, scene_number: int) -> SceneCompletenessEntry:
        scene = next(
            (s for s in job.scenes if s.scene_number == scene_number),
            None,
        )

        if scene is None:
            raise ValueError(f"Job has no scene numbered {scene_number}.")

        # A voiceover generated from the Audio tab leaves each scene's real
        # narration length only on its audio track; fill it in (free, and a
        # no-op once set) so this clip is sized from the real narration, not
        # the script's estimate.
        sync_real_narration_durations(job)

        # Phase 5 (multi-clip scene splitting): a scene whose real
        # narration exceeds Muse's own fixed ~10s single-clip length is
        # generated as several consecutive sub-clips instead - a scene
        # with no real narration duration yet always takes the single-
        # clip path below (matching this class's own existing "fall
        # back to the estimate" behavior for that case), only ever
        # reconsidering the split question once real data exists.
        # Same reasoning as Google Flow's own generate_one().
        if (
            scene.real_narration_duration_seconds is not None
            and SceneClipSplitPlanningService.needs_split(
                scene.real_narration_duration_seconds,
                max_single_clip_seconds=_MUSE_CLIP_DURATION_SECONDS,
            )
        ):
            return self._generate_split_scene(job, scene)

        attempt = self._drive_to_terminal(job, scene)

        if attempt.state == MuseGenerationState.READY:
            self._attach(job, scene, attempt)

            self._extract_reference_for_new_identities(job, scene)

        report = SceneCompletenessService().check(job)

        return next(
            entry for entry in report.entries if entry.scene_number == scene_number
        )

    def generate_all(
        self,
        job: VideoJob,
        *,
        on_scene_complete: Callable[[VideoJob, int], None] | None = None,
    ) -> None:
        """
        Same "skip already-ready scenes" behavior as Google Flow's own
        generate_all() - see that method's own docstring.

        Real-world finding, 2026-09-29: a real Generate All run
        submitted consecutive scenes to Muse with only a few seconds
        between them, and Muse's own chat assistant admitted -
        unprompted - that prompts arriving "back-to-back" while it was
        "still generating" got stacked and delivered as a batch,
        producing duplicate downloads (see _duplicate_scene_number's
        own docstring for the confirmed evidence). generate_all_settle_
        seconds is a deliberate cooldown BETWEEN scenes - never before
        the first one, and skipped for a scene that turns out to
        already be ready - giving Muse's own backend real time to
        finish before this method ever sends it another prompt. This
        reduces how often the duplicate-detection safety net above has
        to actually catch anything; it does not replace it, since a
        cooldown alone cannot guarantee Muse has genuinely finished.
        """

        already_ready = {
            entry.scene_number
            for entry in SceneCompletenessService().check(job).entries
            if entry.status == SceneCompletenessStatus.READY
        }

        is_first_generation = True

        for scene in sorted(job.scenes, key=lambda scene: scene.scene_number):
            if scene.scene_number in already_ready:
                continue

            if not is_first_generation and self._generate_all_settle_seconds > 0:
                self._sleep_fn(self._generate_all_settle_seconds)

            is_first_generation = False

            self.generate_one(job, scene.scene_number)

            if on_scene_complete is not None:
                on_scene_complete(job, scene.scene_number)

    def retry_scene_after_auth(
        self, job: VideoJob, scene_number: int
    ) -> SceneCompletenessEntry:
        """Same reasoning as Google Flow's own retry_scene_after_auth()."""

        scene = next(
            (s for s in job.scenes if s.scene_number == scene_number),
            None,
        )

        if scene is None:
            raise ValueError(f"Job has no scene numbered {scene_number}.")

        stuck_attempt = next(
            (
                attempt
                for attempt in job.muse_generation_attempts
                if attempt.request.scene_number == scene_number
                and attempt.state == MuseGenerationState.AUTH_REQUIRED
            ),
            None,
        )

        if stuck_attempt is None:
            raise ValueError(
                f"Scene {scene_number} has no attempt waiting on authentication."
            )

        self._orchestrator.resume_after_auth(job, stuck_attempt)

        return self.generate_one(job, scene_number)

    def abandon_stuck_attempt(
        self,
        job: VideoJob,
        scene_number: int,
        *,
        force: bool = False,
    ) -> MuseGenerationAttempt:
        """Same reasoning as Google Flow's own abandon_stuck_attempt()."""

        stuck_attempt = next(
            (
                attempt
                for attempt in job.muse_generation_attempts
                if attempt.request.scene_number == scene_number
                and not is_terminal_state(attempt.state)
            ),
            None,
        )

        if stuck_attempt is None:
            raise ValueError(
                f"Scene {scene_number} has no non-terminal attempt to abandon."
            )

        return self._orchestrator.abandon_attempt(job, stuck_attempt, force=force)

    def _generate_split_scene(
        self, job: VideoJob, scene: Scene
    ) -> SceneCompletenessEntry:
        """
        Phase 5 (multi-clip scene splitting), 2026-09-29: a scene whose
        real narration exceeds Muse's fixed ~10s single-clip length is
        generated as several consecutive same-prompt sub-clips instead
        of being destructively trimmed - mirrors Google Flow's own
        _generate_split_scene exactly (see that method's own docstring
        for the full real-world reasoning); the only real differences
        are Muse-specific: SceneClipSplitPlanningService is called with
        Muse's own 10s ceiling and an identity clamp (no discrete
        "verified duration" grid to round up to, since Muse's trim
        mechanism already hits any sub-10s target exactly), and each
        sub-clip's own prompt-instructed trim (see _submit()'s own
        real-world-finding comment) is resolved per sub-clip via the
        duration_override already threaded through _drive_to_terminal.

        Sub-clips are generated strictly in order: sub-clip N's own
        real last frame becomes sub-clip N+1's FIRST_FRAME reference
        (the same frame-extraction/storage machinery
        _extract_reference_for_new_identities uses for cross-scene
        self-consistency, reused here for intra-scene seam continuity).
        A sub-clip that doesn't reach READY stops the whole scene here -
        already-succeeded sub-clips are simply not attached yet; the
        next generate_one() call resumes exactly where this left off,
        since every sub-clip's own attempt is independently tracked in
        the ledger by (scene_number, clip_sequence_index).
        """

        real_duration = scene.real_narration_duration_seconds
        assert real_duration is not None  # narrowed by generate_one()'s own check

        durations = SceneClipSplitPlanningService.plan(
            real_duration,
            max_single_clip_seconds=_MUSE_CLIP_DURATION_SECONDS,
            clamp=lambda seconds: seconds,
        )

        sub_clip_prompt_texts = self._resolve_sub_clip_prompt_texts(
            job, scene, durations
        )

        successful_attempts: list[MuseGenerationAttempt] = []
        seam_reference_path: str | None = None

        for index, duration in enumerate(durations):
            extra_references: list[MuseReferenceAsset] = []

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
                prompt_override=(
                    sub_clip_prompt_texts[index]
                    if sub_clip_prompt_texts is not None
                    else None
                ),
            )

            if attempt.state != MuseGenerationState.READY:
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

    def _resolve_sub_clip_prompt_texts(
        self, job: VideoJob, scene: Scene, durations: list[float]
    ) -> list[str] | None:
        """
        One prompt per sub-clip, each describing only its own real
        time window - None when the shot plan, visual continuity
        bible, or script lock aren't available yet, signaling
        _generate_split_scene() to fall back to the single whole-scene
        prompt for every sub-clip instead. Same reasoning as Google
        Flow's own equivalent.
        """

        prompts = self._resolve_sub_clip_prompts(job, scene, durations)

        return (
            [prompt.prompt_text for prompt in prompts] if prompts is not None else None
        )

    def _resolve_sub_clip_prompts(
        self, job: VideoJob, scene: Scene, durations: list[float]
    ) -> list[ResolvedCinematicPrompt] | None:
        """
        The full resolved sub-clip prompts (not just their text) -
        reused by _resolve_sub_clip_prompt_texts() above for the real
        submission path. Shares the exact same
        CinematicPromptCompilationService.compile_sub_clip_prompts
        Google Flow's own service uses - provider-neutral, so both
        providers' split scenes compile against identical logic rather
        than two implementations that could drift apart.
        """

        if (
            job.cinematic_shot_plan is None
            or job.visual_continuity_bible is None
            or job.script_lock is None
        ):
            return None

        return self._cinematic_prompt_compilation_service.compile_sub_clip_prompts(
            scene=scene,
            shot_plan=job.cinematic_shot_plan,
            visual_continuity_bible=job.visual_continuity_bible,
            production_semantic_brief=job.production_semantic_brief,
            script_lock_hash=job.script_lock.script_content_hash,
            sub_clip_durations=durations,
        )

    def _build_seam_reference_asset(
        self, source_path: str
    ) -> MuseReferenceAsset | None:
        """Best-effort, matching this class's established resilience
        pattern: a missing/unreadable seam-reference file just means
        the next sub-clip submits without it (a visible continuity
        gap, not a correctness failure) rather than blocking the
        scene. Same reasoning as Google Flow's own equivalent."""

        path = Path(source_path)

        if not path.exists():
            logger.warning("Seam reference file no longer exists: %s", source_path)

            return None

        checksum = hashlib.sha256(path.read_bytes()).hexdigest()

        return MuseReferenceAsset(
            source_path=str(path),
            checksum=checksum,
            role=MuseReferenceRole.FIRST_FRAME,
        )

    def _extract_seam_reference(
        self,
        job: VideoJob,
        scene: Scene,
        attempt: MuseGenerationAttempt,
    ) -> str | None:
        """
        Extract sub-clip N's real last frame for sub-clip N+1's own
        FIRST_FRAME reference - the intra-scene counterpart to
        _extract_reference_for_new_identities' cross-scene extraction,
        reusing the exact same frame-extraction/storage primitives.
        Best-effort throughout, same reasoning as that method's own
        docstring. Same reasoning as Google Flow's own equivalent.
        """

        self._sync_extracted_frame_asset_index(job)

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
        attempts: list[MuseGenerationAttempt],
    ) -> None:
        """
        Attach every sub-clip's real, downloaded, validated file as
        this scene's video - attempts[0] becomes the primary
        selected_candidate exactly like _attach()'s own single-clip
        path always has, attempts[1:] become
        additional_ai_generated_sub_clips entries. Same reasoning as
        Google Flow's own equivalent - SceneAssetVideoClipBuilderService
        turns each into its own VideoClip, one per real sub-clip,
        sharing one scene_number and an incrementing clip_sequence_index.
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
                    provider="muse",
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

    def _drive_to_terminal(
        self,
        job: VideoJob,
        scene: Scene,
        *,
        clip_sequence_index: int = 0,
        duration_override: float | None = None,
        extra_reference_assets: list[MuseReferenceAsset] | None = None,
        prompt_override: str | None = None,
    ) -> MuseGenerationAttempt:
        """
        Same orphaned-READY/FAILED/QC_FAILED resubmit logic as Google
        Flow's own _drive_to_terminal() - see that method's own real-
        world-finding comments for why.

        clip_sequence_index/duration_override/extra_reference_assets/
        prompt_override exist for Phase 5 (multi-clip scene splitting)
        alone - every pre-Phase-5 caller uses the defaults
        (0/None/None/None), reproducing this method's exact prior
        behavior. duration_override is threaded through to BOTH
        _submit() and _apply_safety_net_trim() (unlike Google Flow,
        which only needs it in _submit() - Flow's own generation
        already produces the exact requested duration via bucket
        clamping, but Muse's safety-net trim step runs AFTER download
        and needs to know THIS sub-clip's own target, not the whole
        scene's narration, to trim against).
        """

        attempt = MuseGenerationLedgerService.latest_attempt_for_scene(
            job, scene.scene_number, clip_sequence_index=clip_sequence_index
        )

        orphaned_ready = attempt is not None and (
            attempt.state == MuseGenerationState.READY
            and not any(
                state.scene_number == scene.scene_number
                for state in job.scene_asset_states
            )
        )

        if (
            attempt is None
            or orphaned_ready
            or attempt.state
            in (
                MuseGenerationState.FAILED,
                MuseGenerationState.QC_FAILED,
            )
        ):
            attempt = self._submit(
                job,
                scene,
                clip_sequence_index=clip_sequence_index,
                duration_override=duration_override,
                extra_reference_assets=extra_reference_assets,
                prompt_override=prompt_override,
            )
        elif attempt.state in _POLLABLE_STATES:
            attempt = self._poll_until_settled(job, attempt)

        if attempt.state == MuseGenerationState.READY_TO_DOWNLOAD:
            attempt_to_download = attempt
            attempt = self._timed(
                "download",
                scene.scene_number,
                lambda: self._orchestrator.download_attempt(job, attempt_to_download),
            )

        if attempt.state == MuseGenerationState.DOWNLOADED:
            attempt = self._orchestrator.validate_downloaded_attempt(job, attempt)
            MuseGenerationLedgerService.replace_attempt(job, attempt)

        if attempt.state == MuseGenerationState.DOWNLOADED:
            attempt = self._apply_safety_net_trim(
                job, scene, attempt, duration_override=duration_override
            )

        if attempt.state == MuseGenerationState.DOWNLOADED:
            duplicate_scene_number = self._duplicate_scene_number(job, scene, attempt)

            if duplicate_scene_number is not None:
                attempt = attempt.with_transition(
                    MuseGenerationState.UI_CHANGED,
                    detail=(
                        "This download is byte-for-byte identical to "
                        f"scene {duplicate_scene_number}'s own downloaded "
                        "video - Muse appears to have reused a stale or "
                        "queued result instead of generating this scene's "
                        "own distinct video (confirmed real-world finding, "
                        "2026-09-29: Muse can silently batch/stack rapid-"
                        "fire prompts sent close together and deliver "
                        "duplicate results, by its own admission). Abandon "
                        "and retry once Muse is no longer busy."
                    ),
                )
                MuseGenerationLedgerService.replace_attempt(job, attempt)

        if attempt.state == MuseGenerationState.DOWNLOADED:
            # Same "no semantic/multimodal QC exists - promote directly
            # per explicit instruction, review manually" reasoning as
            # Google Flow's own equivalent block.
            attempt = attempt.model_copy(
                update={
                    "qc_result": MuseQCResult(
                        outcome=MuseQCOutcome.PASS,
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
                MuseGenerationState.READY,
                detail=(
                    "Promoted directly to READY: technical validation "
                    "passed and no semantic/multimodal QC is built in "
                    "this codebase. Skipped per explicit instruction; "
                    "review the footage manually."
                ),
            )
            MuseGenerationLedgerService.replace_attempt(job, attempt)

        return attempt

    @staticmethod
    def _duplicate_scene_number(
        job: VideoJob, scene: Scene, attempt: MuseGenerationAttempt
    ) -> int | None:
        """
        Real-world finding, 2026-09-29: during a real Generate All run,
        Muse's own chat assistant admitted - unprompted - that prompts
        sent close together while it was "still generating" got
        stacked and delivered as a batch at the end, rather than each
        being generated independently. Confirmed directly: 3
        consecutive scenes' downloaded files were byte-for-byte
        identical (same SHA-256), while a 4th, later one was genuinely
        different - Muse silently reused/duplicated a result rather
        than rendering each scene's own distinct video. The submit-
        time video-count baseline (see real_adapter.py's own
        _video_count_at_submit) only proves "a new video element
        appeared" - it cannot prove the CONTENT behind that element is
        actually this scene's own, since Muse's own backend can
        deliver a stale/reused result under exactly this element.

        Compares this attempt's own real checksum (computed after
        download, and after any safety-net trim) against every OTHER
        (scene_number, clip_sequence_index) attempt already recorded
        for this job on Muse's own ledger - a match means this is not
        a genuinely distinct video, regardless of how confidently
        observe()/download() reported it ready. Returns the OTHER
        scene's number for a clear operator-facing message, or None
        when no duplicate is found (checksum unset, or genuinely
        unique).
        """

        # Compare the UNTRIMMED download, not the attached file: the same Muse
        # video trimmed to two different scene lengths is two different
        # files, which is how a live project's scene 2 silently received
        # scene 1's footage (2026-10-03).
        this_identity = attempt.source_checksum or attempt.checksum

        if this_identity is None:
            return None

        this_key = (scene.scene_number, attempt.request.clip_sequence_index)

        for other in job.muse_generation_attempts:
            other_key = (
                other.request.scene_number,
                other.request.clip_sequence_index,
            )

            other_identity = other.source_checksum or other.checksum

            if other_key != this_key and other_identity == this_identity:
                return other.request.scene_number

        return None

    def _resolve_target_duration_seconds(
        self, scene: Scene, *, duration_override: float | None = None
    ) -> float:
        """
        The real duration this scene's clip should end up at - real
        narration duration when known (matching Google Flow's own
        resolution order in _submit()), clamped to Muse's fixed
        generation length. Muse can never produce a single clip longer
        than _MUSE_CLIP_DURATION_SECONDS - clamping here only ever
        shortens an already-too-long target, it never asks for more
        than Muse can generate.

        duration_override exists for Phase 5 (multi-clip scene
        splitting) alone: a sub-clip's own planned duration
        (SceneClipSplitPlanningService has already decided it),
        replacing the normal real-narration-vs-estimate computation
        outright, same as Google Flow's own _submit()'s handling of
        this parameter. Every pre-Phase-5 caller omits it.
        """

        if duration_override is not None:
            target_seconds = duration_override
        elif scene.real_narration_duration_seconds is not None:
            target_seconds = scene.real_narration_duration_seconds
        else:
            target_seconds = float(scene.estimated_duration_seconds)

            logger.warning(
                "Scene %s was submitted for Muse video generation before "
                "its real narration duration was known; falling back to "
                "the pre-generation estimate.",
                scene.scene_number,
            )

        return min(target_seconds, _MUSE_CLIP_DURATION_SECONDS)

    def _apply_safety_net_trim(
        self,
        job: VideoJob,
        scene: Scene,
        attempt: MuseGenerationAttempt,
        *,
        duration_override: float | None = None,
    ) -> MuseGenerationAttempt:
        """
        Verified correction for whenever Muse's own prompt-instructed
        trim (see _submit()'s own real-world-finding comment) wasn't
        exact - trims the downloaded file down to the scene's real
        target duration via a real, local ffmpeg pass, then re-
        validates the TRIMMED file so technical_validation/checksum
        reflect what actually gets attached. Best-effort: a trim
        failure is logged and the untrimmed clip is kept rather than
        failing this scene's own generation outright, matching this
        class's established resilience pattern elsewhere (frame
        extraction/reference resolution).

        No-op whenever no trimming utility is wired, the attempt has
        no downloaded_file/technical_validation yet, or the real
        measured duration is already within tolerance of the target -
        i.e. most of the time, once Muse's own prompt-instructed trim
        is working, this never actually re-encodes anything.
        """

        if (
            self._frame_extraction_service is None
            or attempt.downloaded_file is None
            or attempt.technical_validation is None
        ):
            return attempt

        target_seconds = self._resolve_target_duration_seconds(
            scene, duration_override=duration_override
        )
        real_duration = attempt.technical_validation.duration_seconds

        if (
            real_duration is None
            or real_duration <= target_seconds + _SAFETY_NET_TRIM_TOLERANCE_SECONDS
        ):
            return attempt

        source = Path(attempt.downloaded_file)
        trimmed_path = source.with_name(f"{source.stem}_trimmed{source.suffix}")

        try:
            self._frame_extraction_service.trim_to_duration(
                video_path=str(source),
                target_duration_seconds=target_seconds,
                output_path=str(trimmed_path),
            )
        except Exception as error:
            logger.warning(
                "Safety-net trim failed for scene %s (real duration "
                "%.1fs, target %.1fs): %s - keeping the untrimmed clip.",
                scene.scene_number,
                real_duration,
                target_seconds,
                type(error).__name__,
            )

            return attempt

        retrimmed = attempt.model_copy(update={"downloaded_file": str(trimmed_path)})
        annotated = self._orchestrator.validate_downloaded_attempt(job, retrimmed)
        MuseGenerationLedgerService.replace_attempt(job, annotated)

        return annotated

    def _submit(
        self,
        job: VideoJob,
        scene: Scene,
        *,
        clip_sequence_index: int = 0,
        duration_override: float | None = None,
        extra_reference_assets: list[MuseReferenceAsset] | None = None,
        prompt_override: str | None = None,
    ) -> MuseGenerationAttempt:
        """
        clip_sequence_index/duration_override/extra_reference_assets/
        prompt_override exist for Phase 5 (multi-clip scene splitting)
        alone - every pre-Phase-5 caller uses the defaults, reproducing
        this method's exact prior behavior. Same reasoning as Google
        Flow's own _submit() for prompt_override/duration_override;
        extra_reference_assets carries a split scene's own seam
        reference (its predecessor sub-clip's last frame).
        """

        prompt = (
            prompt_override
            if prompt_override is not None
            else ScenePromptExportService._resolve_prompt_text(
                scene, job.cinematic_prompt_package
            )
        )

        target_seconds = self._resolve_target_duration_seconds(
            scene, duration_override=duration_override
        )

        # Same real-world finding as Google Flow's own _submit(): the
        # compiled prompt's "Duration: Ns seconds." text and shot-
        # progression beats are baked in before this real duration is
        # known - re-patched here so the prompt stays truthful about
        # what this scene actually needs, not always Muse's raw fixed
        # length.
        # (the trim instruction for a target shorter than Muse's fixed
        # clip is part of the same shared rules - see
        # VideoProviderRules.finalize_prompt for the live finding behind it)
        prompt = rules_for(VideoProvider.MUSE).finalize_prompt(prompt, target_seconds)

        reference_assets = self._resolve_reference_assets(job, scene) + list(
            extra_reference_assets or []
        )

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
                reference_assets=reference_assets,
                locked_script_hash=(
                    job.script_lock.script_content_hash
                    if job.script_lock is not None
                    else None
                ),
                estimated_cost_usd=self._estimated_cost_usd_per_scene,
                preferred_profile_id=scene.preferred_profile_id,
            ),
        )

        if attempt.state in _POLLABLE_STATES:
            attempt = self._poll_until_settled(job, attempt)

        return attempt

    def _poll_until_settled(
        self, job: VideoJob, attempt: MuseGenerationAttempt
    ) -> MuseGenerationAttempt:
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
        """Same reasoning as Google Flow's own _timed() - logs at the
        one sanctioned boundary outside the provider/browser layer."""

        started_at = time.monotonic()

        try:
            result = fn()
        except FlowOperationTimedOut as error:
            logger.error(
                "muse.%s | scene=%s | TIMED OUT after %.1fs (budget %.1fs)",
                label,
                scene_number,
                error.elapsed_seconds,
                error.timeout_seconds,
            )
            raise
        except Exception as error:
            elapsed = time.monotonic() - started_at
            logger.error(
                "muse.%s | scene=%s | failed after %.1fs | %s",
                label,
                scene_number,
                elapsed,
                type(error).__name__,
            )
            raise

        elapsed = time.monotonic() - started_at
        logger.info(
            "muse.%s | scene=%s | completed in %.1fs",
            label,
            scene_number,
            elapsed,
        )
        return result

    def _attach(
        self,
        job: VideoJob,
        scene: Scene,
        attempt: MuseGenerationAttempt,
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

    def _sync_extracted_frame_asset_index(self, job: VideoJob) -> None:
        """Same reasoning as Google Flow's own equivalent - repoints
        the shared AssetStorageService at THIS job's own persisted
        index before storing or resolving anything."""

        if self._asset_storage_service is not None:
            self._asset_storage_service.asset_index = job.extracted_frame_asset_index

    def _has_valid_reference(
        self, job: VideoJob, identity: CanonicalEntityIdentity
    ) -> bool:
        """Same reasoning as Google Flow's own equivalent - see its
        own docstring for the dangling-reference-id real-world
        finding this guards against."""

        if self._asset_storage_service is None:
            return bool(identity.reference_asset_ids)

        for asset_id in identity.reference_asset_ids:
            asset = self._asset_storage_service.asset_index.get(asset_id)

            if asset is not None and Path(asset.file_path).exists():
                return True

        return False

    def _extract_reference_for_new_identities(
        self,
        job: VideoJob,
        scene: Scene,
    ) -> None:
        """Same reasoning as Google Flow's own equivalent."""

        self._sync_extracted_frame_asset_index(job)

        if (
            self._frame_extraction_service is None
            or self._asset_storage_service is None
        ):
            return

        bible = job.visual_continuity_bible

        if bible is None:
            return

        entry = bible.entry_for_scene(scene.scene_number)

        if entry is None or not entry.on_screen_entity_names:
            return

        new_identities = [
            identity
            for identity in bible.identities
            if identity.name in entry.on_screen_entity_names
            and not self._has_valid_reference(job, identity)
        ]

        if not new_identities:
            return

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
            identity.reference_asset_ids = [str(result.asset.id)]

    def _resolve_reference_assets(
        self, job: VideoJob, scene: Scene
    ) -> list[MuseReferenceAsset]:
        """Same reasoning as Google Flow's own equivalent - no
        duration-forcing rule here (Muse has no duration control to
        force in the first place - see MuseGenerationRequest's own
        docstring)."""

        self._sync_extracted_frame_asset_index(job)

        if self._asset_storage_service is None:
            return []

        bible = job.visual_continuity_bible

        if bible is None:
            return []

        entry = bible.entry_for_scene(scene.scene_number)

        if entry is None or not entry.on_screen_entity_names:
            return []

        featured_identities = [
            identity
            for identity in bible.identities
            if identity.name in entry.on_screen_entity_names
            and identity.reference_asset_ids
        ]

        resolved: list[MuseReferenceAsset] = []

        for identity in featured_identities:
            role = (
                MuseReferenceRole.CHARACTER
                if identity.entity_type == CanonicalEntityType.PERSON
                else MuseReferenceRole.LOCATION
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
                    MuseReferenceAsset(
                        source_path=str(asset_path),
                        checksum=checksum,
                        role=role,
                    )
                )

        return resolved
