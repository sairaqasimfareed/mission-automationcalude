from __future__ import annotations

import pytest

from src.models.shot_planning import (
    CinematicShotPlan,
    ShotAngle,
    ShotMovement,
    ShotSize,
    ShotSpecification,
    TemporalActionBeat,
)


def _shot(scene_number: int, **overrides: object) -> ShotSpecification:
    base: dict[str, object] = dict(
        scene_number=scene_number,
        shot_size=ShotSize.MEDIUM,
        shot_angle=ShotAngle.EYE_LEVEL,
        movement=ShotMovement.STATIC,
        lens="35mm",
        composition="Rule of thirds, subject left.",
        blocking="Captain stands center frame.",
        lighting="Soft morning light.",
        action="The captain surveys the horizon.",
        transition_in="cut",
        transition_out="cut",
        duration_seconds=8.0,
    )
    base.update(overrides)
    return ShotSpecification(**base)


def test_temporal_action_beat_rejects_blank_description() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        TemporalActionBeat(
            start_offset_seconds=0.0, end_offset_seconds=2.0, description="   "
        )


def test_shot_specification_rejects_blank_text_fields() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        _shot(1, lighting="   ")


def test_shot_for_scene_finds_by_scene_number() -> None:
    shot = _shot(2)
    plan = CinematicShotPlan(script_lock_hash="hash123", shots=[shot])

    assert plan.shot_for_scene(2) is shot
    assert plan.shot_for_scene(99) is None


def test_has_exactly_one_shot_per_scene_true_when_unique() -> None:
    plan = CinematicShotPlan(script_lock_hash="hash123", shots=[_shot(1), _shot(2)])

    assert plan.has_exactly_one_shot_per_scene is True


def test_has_exactly_one_shot_per_scene_false_when_duplicated() -> None:
    plan = CinematicShotPlan(script_lock_hash="hash123", shots=[_shot(1), _shot(1)])

    assert plan.has_exactly_one_shot_per_scene is False


def test_empty_plan_has_exactly_one_shot_per_scene_trivially_true() -> None:
    plan = CinematicShotPlan(script_lock_hash="hash123")

    assert plan.has_exactly_one_shot_per_scene is True
