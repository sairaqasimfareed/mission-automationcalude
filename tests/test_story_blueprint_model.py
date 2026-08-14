from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.story_blueprint import StoryBeat, StoryBeatType, StoryBlueprint


def _beat(**overrides: object) -> StoryBeat:
    base: dict[str, object] = dict(
        beat_type=StoryBeatType.HOOK,
        start_seconds=0.0,
        end_seconds=7.0,
        purpose="Open with the central mystery.",
        tension_level=60,
    )
    base.update(overrides)
    return StoryBeat(**base)


def _blueprint(**overrides: object) -> StoryBlueprint:
    base: dict[str, object] = dict(
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        target_duration_seconds=30,
        beats=[
            _beat(
                beat_type=StoryBeatType.HOOK,
                start_seconds=0,
                end_seconds=7,
                tension_level=60,
            ),
            _beat(
                beat_type=StoryBeatType.SETUP,
                start_seconds=7,
                end_seconds=20,
                tension_level=30,
            ),
            _beat(
                beat_type=StoryBeatType.CLIMAX,
                start_seconds=20,
                end_seconds=28,
                tension_level=95,
            ),
            _beat(
                beat_type=StoryBeatType.PAYOFF,
                start_seconds=28,
                end_seconds=30,
                tension_level=50,
            ),
        ],
        prompt_version="story_blueprint_prompt_v1.0.0",
    )
    base.update(overrides)
    return StoryBlueprint(**base)


def test_valid_beat_constructs() -> None:
    beat = _beat()

    assert beat.beat_type == StoryBeatType.HOOK


def test_beat_end_must_be_after_start() -> None:
    with pytest.raises(ValidationError, match="must end after it starts"):
        _beat(start_seconds=10.0, end_seconds=5.0)


def test_beat_rejects_empty_purpose() -> None:
    with pytest.raises(ValidationError):
        _beat(purpose="   ")


def test_valid_blueprint_constructs() -> None:
    blueprint = _blueprint()

    assert len(blueprint.beats) == 4
    assert blueprint.genre_id == "genre.mystery"


def test_genre_id_must_start_with_genre_prefix() -> None:
    with pytest.raises(ValidationError, match="must start with 'genre.'"):
        _blueprint(genre_id="mystery")


def test_blueprint_rejects_overlapping_beats() -> None:
    with pytest.raises(ValidationError, match="cannot overlap"):
        _blueprint(
            beats=[
                _beat(beat_type=StoryBeatType.HOOK, start_seconds=0, end_seconds=10),
                _beat(beat_type=StoryBeatType.SETUP, start_seconds=5, end_seconds=20),
            ]
        )


def test_blueprint_rejects_beats_extending_past_target_duration() -> None:
    with pytest.raises(ValidationError, match="extend past target_duration_seconds"):
        _blueprint(
            target_duration_seconds=10,
            beats=[_beat(start_seconds=0, end_seconds=30)],
        )


def test_blueprint_allows_a_small_rounding_tolerance() -> None:
    blueprint = _blueprint(
        target_duration_seconds=30,
        beats=[_beat(start_seconds=0, end_seconds=30.4)],
    )

    assert blueprint.beats[0].end_seconds == 30.4


def test_blueprint_requires_at_least_one_beat() -> None:
    with pytest.raises(ValidationError):
        _blueprint(beats=[])


def test_tension_curve_is_sorted_by_start_time() -> None:
    blueprint = _blueprint(
        beats=[
            _beat(
                beat_type=StoryBeatType.PAYOFF,
                start_seconds=28,
                end_seconds=30,
                tension_level=50,
            ),
            _beat(
                beat_type=StoryBeatType.HOOK,
                start_seconds=0,
                end_seconds=7,
                tension_level=60,
            ),
        ]
    )

    curve = blueprint.tension_curve

    assert curve == [(0.0, 60), (28.0, 50)]


def test_has_tension_variation_true_when_levels_differ_enough() -> None:
    blueprint = _blueprint()

    assert blueprint.has_tension_variation is True


def test_has_tension_variation_false_when_flat() -> None:
    blueprint = _blueprint(
        beats=[
            _beat(
                beat_type=StoryBeatType.HOOK,
                start_seconds=0,
                end_seconds=10,
                tension_level=70,
            ),
            _beat(
                beat_type=StoryBeatType.CLIMAX,
                start_seconds=10,
                end_seconds=30,
                tension_level=75,
            ),
        ]
    )

    assert blueprint.has_tension_variation is False


def test_has_tension_variation_true_for_a_single_beat() -> None:
    blueprint = _blueprint(
        target_duration_seconds=7,
        beats=[_beat(start_seconds=0, end_seconds=7)],
    )

    assert blueprint.has_tension_variation is True
