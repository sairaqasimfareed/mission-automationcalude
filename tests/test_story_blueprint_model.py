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


def test_phase_9_beat_fields_default_to_empty() -> None:
    beat = _beat()

    assert beat.evidence_fact_ids == []
    assert beat.curiosity_loop_question is None


def test_phase_9_blueprint_field_defaults_to_none() -> None:
    blueprint = _blueprint()

    assert blueprint.research_id is None


def test_beat_curiosity_loop_question_normalizes_blank_to_none() -> None:
    beat = _beat(curiosity_loop_question="   ")

    assert beat.curiosity_loop_question is None


def test_beat_can_carry_evidence_fact_ids() -> None:
    from uuid import uuid4

    fact_id = uuid4()
    beat = _beat(evidence_fact_ids=[fact_id])

    assert beat.evidence_fact_ids == [fact_id]


def test_blueprint_can_carry_research_id() -> None:
    from uuid import uuid4

    research_id = uuid4()
    blueprint = _blueprint(research_id=research_id)

    assert blueprint.research_id == research_id


def test_backward_compatible_round_trip_without_phase_9_fields() -> None:
    blueprint = _blueprint()
    raw = blueprint.model_dump_json()

    reloaded = StoryBlueprint.model_validate_json(raw)

    assert reloaded.research_id is None
    assert all(beat.evidence_fact_ids == [] for beat in reloaded.beats)
    assert all(beat.curiosity_loop_question is None for beat in reloaded.beats)
