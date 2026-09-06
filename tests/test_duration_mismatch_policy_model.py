from __future__ import annotations

import pytest

from src.models.duration_mismatch_policy import (
    DurationMismatchAction,
    SceneDurationMismatch,
)


def test_mismatch_seconds_positive_when_clip_runs_long() -> None:
    mismatch = SceneDurationMismatch(
        scene_number=1,
        planned_duration_seconds=8.0,
        actual_duration_seconds=10.0,
        recommended_action=DurationMismatchAction.TRIM,
    )

    assert mismatch.mismatch_seconds == 2.0


def test_mismatch_seconds_negative_when_clip_runs_short() -> None:
    mismatch = SceneDurationMismatch(
        scene_number=1,
        planned_duration_seconds=8.0,
        actual_duration_seconds=5.0,
        recommended_action=DurationMismatchAction.HOLD_LAST_FRAME,
    )

    assert mismatch.mismatch_seconds == -3.0


def test_approved_workaround_requires_a_note() -> None:
    with pytest.raises(ValueError, match="must record who/why"):
        SceneDurationMismatch(
            scene_number=1,
            planned_duration_seconds=8.0,
            actual_duration_seconds=10.0,
            recommended_action=DurationMismatchAction.APPROVED_WORKAROUND,
        )


def test_approved_workaround_with_a_note_succeeds() -> None:
    mismatch = SceneDurationMismatch(
        scene_number=1,
        planned_duration_seconds=8.0,
        actual_duration_seconds=10.0,
        recommended_action=DurationMismatchAction.APPROVED_WORKAROUND,
        note="Director approved the longer take on 2026-09-06.",
    )

    assert mismatch.note is not None


def test_block_does_not_require_a_note() -> None:
    mismatch = SceneDurationMismatch(
        scene_number=1,
        planned_duration_seconds=8.0,
        actual_duration_seconds=30.0,
        recommended_action=DurationMismatchAction.BLOCK,
    )

    assert mismatch.note is None
