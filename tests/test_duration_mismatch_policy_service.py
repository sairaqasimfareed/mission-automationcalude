from __future__ import annotations

import pytest

from src.models.duration_mismatch_policy import DurationMismatchAction
from src.models.media_strategy import SceneSourceType
from src.models.scene import Scene
from src.models.video_clip import VideoClip
from src.services.duration_mismatch_policy_service import (
    DurationMismatchPolicyService,
)


def _scene(number: int, duration: int) -> Scene:
    return Scene(
        scene_number=number,
        title=f"Scene {number}",
        narration="Narration.",
        visual_prompt="A visual.",
        estimated_duration_seconds=duration,
    )


def _clip(number: int, duration: int) -> VideoClip:
    return VideoClip(
        scene_number=number,
        source_type=SceneSourceType.STOCK_FOOTAGE,
        duration_seconds=duration,
    )


def test_no_mismatch_within_tolerance() -> None:
    service = DurationMismatchPolicyService(tolerance_seconds=0.25)

    mismatches = service.evaluate(scenes=[_scene(1, 8)], clips=[_clip(1, 8)])

    assert mismatches == []


def test_clip_longer_than_planned_recommends_trim() -> None:
    service = DurationMismatchPolicyService(tolerance_seconds=0.25)

    mismatches = service.evaluate(scenes=[_scene(1, 8)], clips=[_clip(1, 10)])

    assert len(mismatches) == 1
    assert mismatches[0].recommended_action == DurationMismatchAction.TRIM
    assert mismatches[0].mismatch_seconds == 2.0


def test_clip_shorter_than_planned_recommends_hold_last_frame() -> None:
    service = DurationMismatchPolicyService(tolerance_seconds=0.25)

    mismatches = service.evaluate(scenes=[_scene(1, 8)], clips=[_clip(1, 6)])

    assert len(mismatches) == 1
    assert mismatches[0].recommended_action == DurationMismatchAction.HOLD_LAST_FRAME
    assert mismatches[0].mismatch_seconds == -2.0


def test_severe_mismatch_recommends_block() -> None:
    service = DurationMismatchPolicyService(tolerance_seconds=0.25, severe_ratio=0.5)

    mismatches = service.evaluate(scenes=[_scene(1, 8)], clips=[_clip(1, 30)])

    assert len(mismatches) == 1
    assert mismatches[0].recommended_action == DurationMismatchAction.BLOCK


def test_scene_with_no_matching_clip_is_skipped() -> None:
    service = DurationMismatchPolicyService()

    mismatches = service.evaluate(scenes=[_scene(1, 8)], clips=[])

    assert mismatches == []


def test_multiple_scenes_evaluated_independently() -> None:
    service = DurationMismatchPolicyService(tolerance_seconds=0.25)

    mismatches = service.evaluate(
        scenes=[_scene(1, 8), _scene(2, 8)],
        clips=[_clip(1, 8), _clip(2, 12)],
    )

    assert len(mismatches) == 1
    assert mismatches[0].scene_number == 2


def test_constructor_rejects_negative_tolerance() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        DurationMismatchPolicyService(tolerance_seconds=-1.0)


def test_constructor_rejects_invalid_severe_ratio() -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        DurationMismatchPolicyService(severe_ratio=1.5)
