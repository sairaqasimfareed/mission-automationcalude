from __future__ import annotations

import math
from collections.abc import Callable

from src.providers.google_flow.locators import (
    VERIFIED_DURATIONS_SECONDS,
    clamp_to_verified_duration,
)

_FLOW_MAX_SINGLE_CLIP_SECONDS = float(max(VERIFIED_DURATIONS_SECONDS))


class SceneClipSplitPlanningService:
    """
    Phase 5 (multi-clip scene splitting): once a scene's real
    narration exceeds a provider's own max single-clip duration, plan
    how many consecutive sub-clips are needed to cover the full real
    narration instead of destructively trimming the script - the same
    real bug class (narration cut to fit a duration decided before the
    real narration existed) Phase 1's audio-first work already fixed
    for the single-clip case.

    Deliberately pure/stateless - no I/O, no randomness, no knowledge
    of scenes/jobs/prompts - so a caller can plan safely before
    spending any real, billed generation, and so this is exhaustively
    unit-testable in isolation before ever touching a real render.

    Provider-neutral since 2026-09-29 (Muse's own Phase 5): the
    max_single_clip_seconds/clamp params default to Google Flow's own
    values, so every existing Flow call site (needs_split(duration),
    plan(duration)) is completely unaffected - Muse's own caller
    passes its fixed ~10s ceiling and an identity clamp instead, since
    Muse has no discrete "verified duration" grid the way Flow does -
    its trim mechanism (prompt instruction + FFmpeg safety-net, see
    MuseSceneVideoGenerationService) can already hit any sub-10s target
    exactly, so there is nothing to round up to.
    """

    @staticmethod
    def needs_split(
        real_narration_duration_seconds: float,
        *,
        max_single_clip_seconds: float = _FLOW_MAX_SINGLE_CLIP_SECONDS,
    ) -> bool:
        """
        True once real narration exceeds the max single clip this
        provider will ever accept in one generation, regardless of how
        a single clamp would round it - the same threshold
        clamp_to_verified_duration's own max() already represents for
        Flow, exposed here as its own named check so a caller never
        has to duplicate that comparison.
        """

        return real_narration_duration_seconds > max_single_clip_seconds

    @classmethod
    def plan(
        cls,
        real_narration_duration_seconds: float,
        *,
        max_single_clip_seconds: float = _FLOW_MAX_SINGLE_CLIP_SECONDS,
        clamp: Callable[[float], float] = clamp_to_verified_duration,
    ) -> list[float]:
        """
        Return the ordered list of sub-clip durations needed to cover
        the full real narration.

        Uses the minimum possible number of sub-clips -
        ceil(total / max_single_clip_seconds), since no single clip can
        ever exceed that ceiling, so fewer, larger clips always beat
        more, smaller ones for keeping seam/reference overhead down -
        divides the real duration evenly across them, then passes each
        share through `clamp` (Flow's own clamp_to_verified_duration by
        default, rounding UP to its nearest verified bucket; Muse's
        caller passes an identity function instead, since any sub-10s
        target is already achievable exactly). Because Flow's own
        clamp only ever rounds up, never down, the sum of planned
        sub-clips always covers at least the full real narration for
        Flow - the same "rounding up can't itself cause an overshoot"
        reasoning clamp_to_verified_duration's own docstring already
        established, just applied per sub-clip here. For Muse's
        identity clamp, the even division itself already covers the
        real narration exactly, with nothing to round.

        A narration that does not need splitting at all returns a
        single-element list (`clamp`'s own result) - the exact
        behavior every scene had before Phase 5 existed.
        """

        if real_narration_duration_seconds <= 0:
            raise ValueError(
                "Split planning requires a positive real narration duration."
            )

        if not cls.needs_split(
            real_narration_duration_seconds,
            max_single_clip_seconds=max_single_clip_seconds,
        ):
            return [float(clamp(real_narration_duration_seconds))]

        sub_clip_count = math.ceil(
            real_narration_duration_seconds / max_single_clip_seconds
        )

        even_share = real_narration_duration_seconds / sub_clip_count

        return [float(clamp(even_share)) for _ in range(sub_clip_count)]
