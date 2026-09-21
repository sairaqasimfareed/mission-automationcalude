from __future__ import annotations

import math

from src.providers.google_flow.locators import (
    VERIFIED_DURATIONS_SECONDS,
    clamp_to_verified_duration,
)


class SceneClipSplitPlanningService:
    """
    Phase 5 (multi-clip scene splitting): once a scene's real
    narration exceeds Google Flow's own max single-clip duration
    (VERIFIED_DURATIONS_SECONDS' own ceiling, currently 8s), plan how
    many consecutive sub-clips are needed to cover the full real
    narration instead of destructively trimming the script - the same
    real bug class (narration cut to fit a duration decided before the
    real narration existed) Phase 1's audio-first work already fixed
    for the single-clip case.

    Deliberately pure/stateless - no I/O, no randomness, no knowledge
    of scenes/jobs/prompts - so a caller can plan safely before
    spending any real, billed generation, and so this is exhaustively
    unit-testable in isolation before ever touching a real render.
    """

    @staticmethod
    def needs_split(real_narration_duration_seconds: float) -> bool:
        """
        True once real narration exceeds the max single clip Flow will
        ever accept, regardless of how a single clamp would round it -
        the same threshold clamp_to_verified_duration's own max()
        already represents, exposed here as its own named check so a
        caller never has to duplicate that comparison.
        """

        return real_narration_duration_seconds > max(VERIFIED_DURATIONS_SECONDS)

    @classmethod
    def plan(cls, real_narration_duration_seconds: float) -> list[float]:
        """
        Return the ordered list of sub-clip durations (each a real
        VERIFIED_DURATIONS_SECONDS value) needed to cover the full
        real narration.

        Uses the minimum possible number of sub-clips -
        ceil(total / max_bucket), since no single clip can ever exceed
        the max bucket, so fewer, larger clips always beat more,
        smaller ones for keeping seam/reference overhead down - divides
        the real duration evenly across them, then clamps each share
        UP to its own nearest verified bucket via
        clamp_to_verified_duration, the same single source of truth
        every other duration decision in this codebase already uses.
        Because each bucket only ever clamps up, never down, the sum
        of planned sub-clips always covers at least the full real
        narration - the same "rounding up can't itself cause an
        overshoot" reasoning clamp_to_verified_duration's own
        docstring already established, just applied per sub-clip here.

        A narration that does not need splitting at all returns a
        single-element list (clamp_to_verified_duration's own result)
        - the exact behavior every scene had before Phase 5 existed.
        """

        if real_narration_duration_seconds <= 0:
            raise ValueError(
                "Split planning requires a positive real narration duration."
            )

        if not cls.needs_split(real_narration_duration_seconds):
            return [float(clamp_to_verified_duration(real_narration_duration_seconds))]

        max_bucket = max(VERIFIED_DURATIONS_SECONDS)

        sub_clip_count = math.ceil(real_narration_duration_seconds / max_bucket)

        even_share = real_narration_duration_seconds / sub_clip_count

        return [
            float(clamp_to_verified_duration(even_share)) for _ in range(sub_clip_count)
        ]
