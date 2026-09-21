from __future__ import annotations

import pytest

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
        # ceil(8.1 / 8) = 2 sub-clips; 8.1 / 2 = 4.05, clamps up to 6s
        # each - total 12s comfortably covers the real 8.1s narration.
        assert SceneClipSplitPlanningService.plan(8.1) == [6.0, 6.0]

    def test_nine_seconds_plans_two_six_second_clips(self) -> None:
        # ceil(9 / 8) = 2; 9 / 2 = 4.5, clamps up to 6s each.
        assert SceneClipSplitPlanningService.plan(9.0) == [6.0, 6.0]

    def test_twelve_seconds_plans_two_six_second_clips_exactly(self) -> None:
        # ceil(12 / 8) = 2; 12 / 2 = 6.0 exactly, no rounding needed.
        assert SceneClipSplitPlanningService.plan(12.0) == [6.0, 6.0]

    def test_just_past_twelve_seconds_needs_two_eight_second_clips(self) -> None:
        # ceil(12.1 / 8) = 2; 12.1 / 2 = 6.05, clamps up to 8s each.
        assert SceneClipSplitPlanningService.plan(12.1) == [8.0, 8.0]

    def test_sixteen_seconds_plans_two_eight_second_clips_exactly(self) -> None:
        # ceil(16 / 8) = 2; 16 / 2 = 8.0 exactly.
        assert SceneClipSplitPlanningService.plan(16.0) == [8.0, 8.0]

    def test_just_past_sixteen_seconds_needs_three_clips(self) -> None:
        # ceil(16.1 / 8) = 3; 16.1 / 3 ~= 5.37, clamps up to 6s each -
        # total 18s comfortably covers the real 16.1s narration.
        assert SceneClipSplitPlanningService.plan(16.1) == [6.0, 6.0, 6.0]

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
