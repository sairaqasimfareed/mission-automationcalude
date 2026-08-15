from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.generated_script import GeneratedScript, ScriptSegment
from src.models.story_blueprint import StoryBeatType


def _segment(**overrides: object) -> ScriptSegment:
    base: dict[str, object] = dict(
        segment_number=1,
        start_seconds=0.0,
        end_seconds=7.0,
        narrative_function=StoryBeatType.HOOK,
        narration="The crew vanished without a trace.",
        tension_level=60,
    )
    base.update(overrides)
    return ScriptSegment(**base)


def _script(**overrides: object) -> GeneratedScript:
    base: dict[str, object] = dict(
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        target_duration_seconds=30,
        segments=[
            _segment(
                segment_number=1,
                start_seconds=0,
                end_seconds=7,
                narrative_function=StoryBeatType.HOOK,
                narration="The crew vanished without a trace.",
            ),
            _segment(
                segment_number=2,
                start_seconds=7,
                end_seconds=30,
                narrative_function=StoryBeatType.PAYOFF,
                narration="The most likely theory is a waterspout scare.",
            ),
        ],
        prompt_version="script_generation_prompt_v1.0.0",
    )
    base.update(overrides)
    return GeneratedScript(**base)


def test_valid_segment_constructs() -> None:
    segment = _segment()

    assert segment.narrative_function == StoryBeatType.HOOK


def test_segment_rejects_empty_narration() -> None:
    with pytest.raises(ValidationError):
        _segment(narration="   ")


def test_segment_end_must_be_after_start() -> None:
    with pytest.raises(ValidationError, match="must end after it starts"):
        _segment(start_seconds=10.0, end_seconds=5.0)


def test_segment_related_curiosity_loop_none_when_blank() -> None:
    segment = _segment(related_curiosity_loop="  ")

    assert segment.related_curiosity_loop is None


def test_segment_word_count() -> None:
    segment = _segment(narration="One two three four five.")

    assert segment.word_count == 5


def test_valid_script_constructs() -> None:
    script = _script()

    assert len(script.segments) == 2


def test_genre_id_must_start_with_genre_prefix() -> None:
    with pytest.raises(ValidationError, match="must start with 'genre.'"):
        _script(genre_id="mystery")


def test_script_rejects_overlapping_segments() -> None:
    with pytest.raises(ValidationError, match="cannot overlap"):
        _script(
            segments=[
                _segment(segment_number=1, start_seconds=0, end_seconds=10),
                _segment(segment_number=2, start_seconds=5, end_seconds=20),
            ]
        )


def test_script_requires_at_least_one_segment() -> None:
    with pytest.raises(ValidationError):
        _script(segments=[])


def test_full_narration_joins_in_chronological_order() -> None:
    script = _script(
        segments=[
            _segment(
                segment_number=2,
                start_seconds=7,
                end_seconds=30,
                narration="Second segment.",
            ),
            _segment(
                segment_number=1,
                start_seconds=0,
                end_seconds=7,
                narration="First segment.",
            ),
        ]
    )

    assert script.full_narration == "First segment. Second segment."


def test_word_count_sums_all_segments() -> None:
    script = _script(
        segments=[
            _segment(
                segment_number=1, start_seconds=0, end_seconds=7, narration="One two."
            ),
            _segment(
                segment_number=2,
                start_seconds=7,
                end_seconds=30,
                narration="Three four five.",
            ),
        ]
    )

    assert script.word_count == 5
