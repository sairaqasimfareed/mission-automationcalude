from __future__ import annotations

import pytest

from src.providers.google_flow.locators import clamp_to_verified_duration
from src.services.scene_clip_split_planning_service import (
    SceneClipSplitPlanningService,
)


class TestNeedsSplit:
    def test_short_narration_does_not_need_a_split(self) -> None:
        assert SceneClipSplitPlanningService.needs_split(5.0) is False

    def test_narration_exactly_at_the_max_bucket_does_not_need_a_split(self) -> None:
        assert SceneClipSplitPlanningService.needs_split(8.0) is False

    def test_narration_past_the_max_bucket_needs_a_split(self) -> None:
        assert SceneClipSplitPlanningService.needs_split(8.1) is True


class TestPlan:
    def test_rejects_non_positive_duration(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            SceneClipSplitPlanningService.plan(0.0)

        with pytest.raises(ValueError, match="positive"):
            SceneClipSplitPlanningService.plan(-1.0)

    def test_a_narration_under_the_max_bucket_plans_a_single_clamped_clip(
        self,
    ) -> None:
        # 5s clamps up to the next verified bucket (6s) - matches
        # clamp_to_verified_duration's own behavior exactly, since no
        # split is needed at all.
        assert SceneClipSplitPlanningService.plan(5.0) == [6.0]

    def test_a_narration_exactly_at_the_max_bucket_plans_one_clip(self) -> None:
        assert SceneClipSplitPlanningService.plan(8.0) == [8.0]

    def test_just_past_the_max_bucket_plans_two_clips(self) -> None:
        # ceil(8.1 / 8) = 2 sub-clips. The cheapest pair of verified
        # lengths covering 8.1s is 6+4 = 10s (6+6 = 12s wasted 2 more).
        assert SceneClipSplitPlanningService.plan(8.1) == [6.0, 4.0]

    def test_nine_seconds_plans_six_plus_four(self) -> None:
        # Real case from a live project: 9s used to plan 6+6 = 12s
        # (4.5s even shares rounded up to 6s each). 6+4 = 10s covers it.
        assert SceneClipSplitPlanningService.plan(9.0) == [6.0, 4.0]

    def test_ten_seconds_plans_six_plus_four_exactly(self) -> None:
        assert SceneClipSplitPlanningService.plan(10.0) == [6.0, 4.0]

    def test_twelve_seconds_stays_an_even_six_plus_six(self) -> None:
        # 8+4 also totals exactly 12s - the tie goes to the more even
        # split (smaller longest clip).
        assert SceneClipSplitPlanningService.plan(12.0) == [6.0, 6.0]

    def test_just_past_twelve_seconds_needs_eight_plus_six(self) -> None:
        # 8+6 = 14s covers 12.1s; the old plan used 8+8 = 16s.
        assert SceneClipSplitPlanningService.plan(12.1) == [8.0, 6.0]

    def test_sixteen_seconds_plans_two_eight_second_clips_exactly(self) -> None:
        assert SceneClipSplitPlanningService.plan(16.0) == [8.0, 8.0]

    def test_just_past_sixteen_seconds_needs_three_clips(self) -> None:
        # ceil(16.1 / 8) = 3; 18s is the cheapest total, and 6+6+6 beats
        # 8+6+4 on evenness.
        assert SceneClipSplitPlanningService.plan(16.1) == [6.0, 6.0, 6.0]

    def test_twenty_seconds_plans_eight_eight_four_exactly(self) -> None:
        assert SceneClipSplitPlanningService.plan(20.0) == [8.0, 8.0, 4.0]

    @pytest.mark.parametrize(
        "narration_seconds", [8.1, 9.0, 10.0, 11.0, 12.0, 12.1, 14.0, 16.5, 20.0]
    )
    def test_the_plan_is_never_more_wasteful_than_the_even_split_it_replaced(
        self, narration_seconds: float
    ) -> None:
        import math

        count = math.ceil(narration_seconds / 8.0)
        even_share = narration_seconds / count
        old_total = sum(
            float(clamp_to_verified_duration(even_share)) for _ in range(count)
        )

        plan = SceneClipSplitPlanningService.plan(narration_seconds)

        assert len(plan) == count  # never more seams
        assert sum(plan) <= old_total
        assert plan == sorted(plan, reverse=True)

    @pytest.mark.parametrize(
        "narration_seconds",
        [8.5, 9.9, 11.0, 12.0, 15.9, 20.0, 24.0, 30.5],
    )
    def test_the_planned_total_always_covers_the_real_narration(
        self, narration_seconds: float
    ) -> None:
        """Across a range of real narration lengths, the sum of
        planned sub-clip durations must never fall short of the real
        narration - the one invariant that actually matters (never
        destructively trim), regardless of the exact split chosen."""

        plan = SceneClipSplitPlanningService.plan(narration_seconds)

        assert sum(plan) >= narration_seconds

    @pytest.mark.parametrize(
        "narration_seconds",
        [8.5, 9.9, 11.0, 12.0, 15.9, 20.0, 24.0, 30.5],
    )
    def test_every_planned_sub_clip_is_a_verified_flow_duration(
        self, narration_seconds: float
    ) -> None:
        plan = SceneClipSplitPlanningService.plan(narration_seconds)

        assert all(duration in (4.0, 6.0, 8.0) for duration in plan)


class TestPlanForAnotherProvider:
    """
    Muse (2026-09-29) has no discrete "verified duration" grid the way
    Flow does - it always generates a fixed ~10s clip, and its trim
    mechanism (prompt instruction + FFmpeg safety-net) can already hit
    any sub-10s target exactly. A caller passing max_single_clip_seconds
    and an identity clamp gets Muse's own splitting behavior without a
    second, near-duplicate planning service.
    """

    @staticmethod
    def _identity(seconds: float) -> float:
        return seconds

    def test_narration_under_the_provider_max_does_not_need_a_split(self) -> None:
        assert (
            SceneClipSplitPlanningService.needs_split(9.0, max_single_clip_seconds=10.0)
            is False
        )

    def test_narration_past_the_provider_max_needs_a_split(self) -> None:
        assert (
            SceneClipSplitPlanningService.needs_split(
                13.0, max_single_clip_seconds=10.0
            )
            is True
        )

    def test_thirteen_seconds_plans_two_exact_sub_clips_with_no_rounding(self) -> None:
        # ceil(13 / 10) = 2 sub-clips; 13 / 2 = 6.5 each, unrounded -
        # this is exactly scene 10's real case that prompted this fix.
        plan = SceneClipSplitPlanningService.plan(
            13.0, max_single_clip_seconds=10.0, clamp=self._identity
        )

        assert plan == [6.5, 6.5]
        assert sum(plan) == 13.0  # exact, no overshoot needed

    def test_a_narration_under_the_provider_max_plans_a_single_unrounded_clip(
        self,
    ) -> None:
        plan = SceneClipSplitPlanningService.plan(
            7.0, max_single_clip_seconds=10.0, clamp=self._identity
        )

        assert plan == [7.0]
