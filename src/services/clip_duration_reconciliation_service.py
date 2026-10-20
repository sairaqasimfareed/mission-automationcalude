from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from src.models.media_strategy import SceneSourceType
from src.models.scene import Scene
from src.models.video_clip import VideoClip
from src.services.asset_provenance_service import AssetProvenanceService
from src.services.frame_extraction_service import FrameExtractionService
from src.shared.logger import logger

# Real-world finding, 2026-09-30: nothing in the render pipeline ever
# reconciled a stock/manual clip's real duration against its scene's
# real, measured narration length (Scene.real_narration_duration_seconds,
# populated by VoicePipelineStage before AssetPipelineStage ever runs -
# see that stage's own real-world-finding comment). AI-generated clips
# don't have this gap: Google Flow requests a clip duration already
# rounded up to cover the real narration
# (google_flow.locators.clamp_to_verified_duration), and Muse has its
# own post-download safety-net trim
# (MuseSceneVideoGenerationService._apply_safety_net_trim) for its
# fixed ~10s clips. Stock footage and manual uploads have neither - a
# clip's duration is whatever the acquired file happens to be. This is
# that reconciliation, built the same way Muse's own safety net was:
# trim a clip that runs long (a real, local ffmpeg pass, same
# FrameExtractionService.trim_to_duration() Muse already uses); a clip
# that runs short is not silently extended - hold-last-frame is a real
# editorial decision, not a purely technical one, so this surfaces a
# clear, actionable warning or error instead, scaled to how severe the
# shortfall is.
_TOLERANCE_SECONDS = 0.5

# The next scene's picture - and so its voice - starts this long BEFORE this clip ends (the crossfade
# between two scenes overlaps them; 0.7 s in the genres' own transitions). A voice therefore has to
# finish this much before the clip does, or it runs into the next voice (seen live, 2026-10-20: a clip
# only 0.6 s longer than its voice still overlapped the next one).
_TRANSITION_ALLOWANCE_SECONDS = 0.7

# Matches DurationMismatchPolicyService's own default severe_ratio -
# same judgment call (a shortfall exceeding half the scene's real
# narration length is severe enough to block rather than warn), reused
# here rather than re-derived, though this service compares against
# real narration duration rather than that service's planned estimate,
# so the two are not interchangeable.
_SEVERE_SHORTFALL_RATIO = 0.5

# AI-generated clips already have their own reconciliation (see the
# module docstring above) - reconciling them a second time here would
# be redundant at best and could conflict with Muse's own already-
# completed safety-net trim at worst.
_RECONCILABLE_SOURCE_TYPES = frozenset(
    {
        SceneSourceType.MANUAL_UPLOAD,
        SceneSourceType.STOCK_FOOTAGE,
        SceneSourceType.LOCAL_LIBRARY,
        SceneSourceType.IMAGE_TO_VIDEO,
    }
)


@dataclass(frozen=True, slots=True)
class ClipDurationReconciliationResult:
    """
    Outcome of reconciling one job's clips against their scenes' real
    narration durations.

    clips is always the full, ordered input list (trimmed clips
    replaced in place, everything else passed through unchanged) - a
    caller can always safely assign it straight back onto
    VideoJob.video_clips. warnings are non-blocking (a mild shortfall);
    errors are severe shortfalls a caller should treat as a stage
    failure, matching this codebase's existing StageResult convention.
    """

    clips: list[VideoClip]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class ClipDurationReconciliationService:
    """
    Reconciles stock/manual clip durations against real narration.

    Deliberately separate from DurationMismatchPolicyService, which
    compares a scene's word-count PLAN (estimated_duration_seconds)
    against a clip's real duration for Quality Center's own advisory
    display - a genuinely different, still-valid question. This
    service compares the scene's REAL, measured narration duration
    against the clip's real duration, and - unlike that service -
    actually executes a fix rather than only recommending one.
    """

    def __init__(
        self,
        *,
        frame_extraction_service: FrameExtractionService | None = None,
        provenance_service: AssetProvenanceService | None = None,
        tolerance_seconds: float = _TOLERANCE_SECONDS,
        severe_shortfall_ratio: float = _SEVERE_SHORTFALL_RATIO,
    ) -> None:
        if tolerance_seconds < 0:
            raise ValueError("Tolerance cannot be negative.")

        if not 0 < severe_shortfall_ratio <= 1:
            raise ValueError("Severe shortfall ratio must be between 0 and 1.")

        self._frame_extraction_service = (
            frame_extraction_service or FrameExtractionService()
        )
        self._provenance_service = provenance_service or AssetProvenanceService()
        self._tolerance_seconds = tolerance_seconds
        self._severe_shortfall_ratio = severe_shortfall_ratio

    def reconcile(
        self,
        *,
        scenes: list[Scene],
        clips: list[VideoClip],
    ) -> ClipDurationReconciliationResult:
        """Trim over-long stock/manual clips; flag ones that run short."""

        scenes_by_number = {scene.scene_number: scene for scene in scenes}

        updated_clips: list[VideoClip] = []
        warnings: list[str] = []
        errors: list[str] = []

        clips_per_scene: dict[int, int] = {}

        for clip in clips:
            clips_per_scene[clip.scene_number] = (
                clips_per_scene.get(clip.scene_number, 0) + 1
            )

        for clip in clips:
            if clip.source_type == SceneSourceType.AI_GENERATE:
                updated_clips.append(
                    self._hold_short_ai_clip(
                        clip=clip,
                        scene=scenes_by_number.get(clip.scene_number),
                        single_clip=clips_per_scene[clip.scene_number] == 1,
                        warnings=warnings,
                    )
                )
                continue

            if clip.source_type not in _RECONCILABLE_SOURCE_TYPES:
                updated_clips.append(clip)
                continue

            scene = scenes_by_number.get(clip.scene_number)

            # A visual-only scene has no narration to measure: its fixed length is the target.
            target = (
                float(scene.estimated_duration_seconds)
                if scene is not None and scene.silent
                else (scene.real_narration_duration_seconds if scene else None)
            )

            if scene is None or target is None:
                updated_clips.append(clip)
                continue

            narration_seconds = target
            clip_seconds = float(clip.duration_seconds)
            difference = clip_seconds - narration_seconds

            if difference > self._tolerance_seconds:
                updated_clips.append(
                    self._trim(clip=clip, target_seconds=narration_seconds)
                )
                continue

            if difference < -self._tolerance_seconds:
                shortfall = -difference

                message = (
                    f"Scene {clip.scene_number}: the selected clip "
                    f"({clip_seconds:.1f}s) is {shortfall:.1f}s shorter "
                    f"than its real narration ({narration_seconds:.1f}s)"
                )

                if shortfall > narration_seconds * self._severe_shortfall_ratio:
                    errors.append(
                        message + " - choose a longer clip or shorten "
                        "the narration before rendering."
                    )
                else:
                    warnings.append(
                        message + " - narration may run past this "
                        "scene's video into the next scene."
                    )

                updated_clips.append(clip)
                continue

            updated_clips.append(clip)

        return ClipDurationReconciliationResult(
            clips=updated_clips,
            warnings=warnings,
            errors=errors,
        )

    def _hold_short_ai_clip(
        self,
        *,
        clip: VideoClip,
        scene: Scene | None,
        single_clip: bool,
        warnings: list[str],
    ) -> VideoClip:
        """
        An AI clip is sized to the narration when it is generated, but the voice can be made
        again afterwards (another voice, edited text) and come out longer. The voice then runs
        past the end of its picture - into the next scene's voice (two voices at once) and out
        of step with every picture after it. Hold the clip's last frame for the missing seconds
        so the scene is as long as its voice. Best effort, like _trim: a failure keeps the clip.
        A scene made of several clips is left alone (its parts are sized together).
        """

        if scene is None or scene.silent or not single_clip or clip.local_file is None:
            return clip

        narration = scene.real_narration_duration_seconds

        if narration is None:
            return clip

        needed = narration + _TRANSITION_ALLOWANCE_SECONDS
        shortfall = needed - float(clip.duration_seconds)

        if shortfall <= self._tolerance_seconds:
            return clip

        source = Path(clip.local_file)
        target_seconds = math.ceil(needed)
        held_path = source.with_name(f"{source.stem}_held{source.suffix}")

        try:
            self._frame_extraction_service.hold_to_duration(
                video_path=str(source),
                target_duration_seconds=float(target_seconds),
                output_path=str(held_path),
            )
        except Exception as error:
            logger.warning(
                "Holding the last frame failed for scene %s (clip %.1fs, narration %.1fs): "
                "%s - keeping the clip as it is.",
                clip.scene_number,
                float(clip.duration_seconds),
                narration,
                type(error).__name__,
            )
            warnings.append(
                f"Scene {clip.scene_number}: the voice ({narration:.1f}s) is longer than "
                f"its clip ({float(clip.duration_seconds):.1f}s) and the clip could not be "
                "extended - the voice may run into the next scene."
            )

            return clip

        warnings.append(
            f"Scene {clip.scene_number}: the voice ({narration:.1f}s) is longer than its "
            f"clip ({float(clip.duration_seconds):.1f}s), so the last picture is held for "
            f"{shortfall:.1f}s. Generate this clip again to fill the time with new motion."
        )

        return clip.model_copy(
            update={
                "local_file": str(held_path),
                "duration_seconds": target_seconds,
                "checksum": self._provenance_service.compute_checksum(str(held_path)),
            }
        )

    def _trim(self, *, clip: VideoClip, target_seconds: float) -> VideoClip:
        """
        Best-effort trim: a failure is logged and the untrimmed clip is
        kept rather than failing the whole render, matching
        MuseSceneVideoGenerationService._apply_safety_net_trim's own
        resilience pattern.
        """

        if clip.local_file is None:
            return clip

        source = Path(clip.local_file)
        trimmed_path = source.with_name(f"{source.stem}_trimmed{source.suffix}")

        try:
            self._frame_extraction_service.trim_to_duration(
                video_path=str(source),
                target_duration_seconds=target_seconds,
                output_path=str(trimmed_path),
            )
        except Exception as error:
            logger.warning(
                "Duration reconciliation trim failed for scene %s "
                "(clip %.1fs, target %.1fs): %s - keeping the "
                "untrimmed clip.",
                clip.scene_number,
                float(clip.duration_seconds),
                target_seconds,
                type(error).__name__,
            )

            return clip

        checksum = self._provenance_service.compute_checksum(str(trimmed_path))

        return clip.model_copy(
            update={
                "local_file": str(trimmed_path),
                "duration_seconds": max(1, round(target_seconds)),
                "checksum": checksum,
            }
        )
