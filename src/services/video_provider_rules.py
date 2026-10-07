from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

from src.models.scene import Scene
from src.models.video_job import VideoJob
from src.models.video_provider import VideoProvider
from src.providers.google_flow.locators import (
    VERIFIED_DURATIONS_SECONDS,
    clamp_to_verified_duration,
)
from src.services.scene_clip_split_planning_service import SceneClipSplitPlanningService
from src.services.scene_video_generation_service import (
    _DURATION_STATEMENT_PATTERN,
    _bound_flat_action_to_real_duration,
    _extend_last_beat_to_real_duration,
)

# Muse always generates one fixed ~10s clip - it has no duration control to
# size it (see MuseGenerationRequest). Anything shorter is reached by
# trimming: first by asking Muse itself in the prompt, then by an FFmpeg
# safety net. A target within this tolerance of 10s is "close enough" and
# gets neither the instruction nor the correction.
MUSE_CLIP_DURATION_SECONDS = 10.0
MUSE_SAFETY_NET_TRIM_TOLERANCE_SECONDS = 0.5

# Live, 2026-10-07 (Remedy): the "Also trim the generated 10 seconds video to only
# N seconds video." line made Muse build a full 10-second clip and cut it, so the
# end of what it had planned was lost - a woman mid-sentence, then a different
# scene (3-4 places in one video). Pasted into Muse without that line, our own
# prompts came back at exactly their stated length: "Duration: 8 seconds" -> 8 s,
# "Duration: 3 seconds" -> 3 s, and "generate a 4 second ..." -> 4 s. So the length
# is now only stated (the "Duration: N seconds." line already in every prompt) and
# the FFmpeg safety net trims a clip that still comes back too long. Flip this to
# True to send the trim instruction again.
MUSE_SEND_TRIM_INSTRUCTION = False

# The shortest clip Muse is ever asked for, 2026-10-04. A one-word scene
# (~1s of narration) would otherwise be a ~1s clip - shorter than the
# crossfades around it, and the case Muse's "trim to N seconds" handles
# least reliably. Google Flow already has an effective 4s minimum (its
# shortest verified duration), so this only brings Muse in line. The extra
# seconds play as silent picture after the narration (the voice stays
# aligned to the scene start; music continues underneath). Applies to a
# scene's single clip only - split sub-clips are always much longer.
MUSE_MIN_CLIP_SECONDS = 3.0

_MAX_FLOW_CLIP_SECONDS = float(max(VERIFIED_DURATIONS_SECONDS))


def _identity(seconds: float) -> float:
    return seconds


def muse_target_seconds(seconds: float) -> float:
    """
    The length asked of Muse for a clip needing `seconds`: ROUNDED UP to a whole
    second, never past its fixed 10s.

    Muse is told "trim to only N seconds" in whole seconds, and this used to
    print the nearest one - so a 7.38s narration got a 7s clip and a 4.32s one
    got 4s (live, 2026-10-06): the voice ran past the picture. A little silent
    picture at the end of a scene is harmless; narration running over the next
    scene's picture is not. (The tiny epsilon keeps an exact 7.0 at 7.)
    """

    return float(min(math.ceil(seconds - 1e-9), MUSE_CLIP_DURATION_SECONDS))


@dataclass(frozen=True)
class VideoProviderRules:
    """
    How one video provider sizes clips and words their prompts.

    The single place these rules live, so the automated submission path
    and the prompt previews (Prompts tab, Content tab) cannot drift apart:
    the previews show exactly what a submission would send.
    """

    provider: VideoProvider

    @property
    def display_name(self) -> str:
        return "Muse" if self.provider == VideoProvider.MUSE else "Google Flow"

    @property
    def max_single_clip_seconds(self) -> float:
        return (
            MUSE_CLIP_DURATION_SECONDS
            if self.provider == VideoProvider.MUSE
            else _MAX_FLOW_CLIP_SECONDS
        )

    @property
    def summary(self) -> str:
        """Short label for the UI, e.g. "Muse - 10s clips"."""

        if self.provider == VideoProvider.MUSE:
            return f"Muse - {MUSE_CLIP_DURATION_SECONDS:.0f}s clips, trimmed to length"

        return f"Google Flow - up to {_MAX_FLOW_CLIP_SECONDS:.0f}s clips (4/6/8s)"

    def needs_split(self, narration_seconds: float) -> bool:
        return SceneClipSplitPlanningService.needs_split(
            narration_seconds,
            max_single_clip_seconds=self.max_single_clip_seconds,
        )

    def plan_clips(self, narration_seconds: float) -> list[float]:
        """The clip lengths needed to cover the narration (one element
        unless it must be split)."""

        if self.provider == VideoProvider.MUSE:
            return SceneClipSplitPlanningService.plan(
                narration_seconds,
                max_single_clip_seconds=MUSE_CLIP_DURATION_SECONDS,
                clamp=_identity,
            )

        return SceneClipSplitPlanningService.plan(narration_seconds)

    def single_clip_seconds(self, narration_seconds: float) -> float:
        """The length of the one clip generated for a scene that does not
        need splitting: Flow rounds up to its verified grid; Muse's clip
        is trimmed to the exact narration length, but never below
        MUSE_MIN_CLIP_SECONDS."""

        if self.provider == VideoProvider.MUSE:
            return muse_target_seconds(max(narration_seconds, MUSE_MIN_CLIP_SECONDS))

        return float(clamp_to_verified_duration(narration_seconds))

    def finalize_prompt(self, prompt: str, target_seconds: float) -> str:
        """
        The prompt exactly as a submission would send it: its stated
        duration and last shot beat corrected to the real target (both
        are baked in at compile time, before the real narration length
        exists). Muse is no longer sent a trim instruction (see
        MUSE_SEND_TRIM_INSTRUCTION): the stated length is what it follows.
        """

        if self.provider == VideoProvider.MUSE:
            target_seconds = muse_target_seconds(target_seconds)

        prompt = _DURATION_STATEMENT_PATTERN.sub(
            lambda match: f"Duration: {target_seconds:.0f} seconds{match.group(1)}",
            prompt,
        )
        prompt = _extend_last_beat_to_real_duration(prompt, target_seconds)
        prompt = _bound_flat_action_to_real_duration(prompt, target_seconds)

        if (
            self.provider == VideoProvider.MUSE
            and not MUSE_SEND_TRIM_INSTRUCTION
            and not _DURATION_STATEMENT_PATTERN.search(prompt)
        ):
            # A compiled prompt always states its duration, but a scene with no
            # compiled prompt (or a hand-written one) does not - and the stated
            # length is now the ONLY way Muse is told how long to make the clip.
            prompt = f"{prompt}\n\nDuration: {target_seconds:.0f} seconds."

        if (
            self.provider == VideoProvider.MUSE
            and MUSE_SEND_TRIM_INSTRUCTION
            and target_seconds
            < MUSE_CLIP_DURATION_SECONDS - MUSE_SAFETY_NET_TRIM_TOLERANCE_SECONDS
        ):
            # Real-world finding, 2026-09-29: Muse's own agent executes an
            # explicit trim instruction embedded in the prompt (confirmed
            # live: "trim 10 seconds video to only 7 seconds video"
            # produced a genuinely ~7s clip). Asking up front avoids
            # wasting footage on a jump-cut correction most of the time;
            # the FFmpeg safety net is the fallback, never the primary.
            prompt = (
                f"{prompt}\n\nAlso trim the generated "
                f"{MUSE_CLIP_DURATION_SECONDS:.0f} seconds video to "
                f"only {target_seconds:.0f} seconds video."
            )

        return prompt


def rules_for(provider: VideoProvider) -> VideoProviderRules:
    return VideoProviderRules(provider)


def resolve_scene_video_provider(
    job: VideoJob,
    scene: Scene,
    provider_name_for_profile: Callable[[str], str | None] | None = None,
) -> VideoProvider:
    """
    Which provider generates this scene.

    An explicit per-scene account choice (Scene.preferred_profile_id)
    wins - it names both provider and account. Otherwise the project's
    own video_provider decides. provider_name_for_profile maps a profile
    id to its provider name; a profile it cannot resolve falls through to
    the project default rather than guessing.
    """

    if scene.preferred_profile_id is not None and provider_name_for_profile is not None:
        provider_name = provider_name_for_profile(scene.preferred_profile_id)

        if provider_name is not None:
            return (
                VideoProvider.MUSE
                if provider_name.strip().lower() == "muse"
                else VideoProvider.GOOGLE_FLOW
            )

    return job.video_provider
