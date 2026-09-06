from __future__ import annotations

import pytest

from src.models.production_semantic_brief import (
    ProductionSemanticBrief,
    ProductionSemanticSegment,
)


def _segment(number: int, start: float, end: float, **overrides: object) -> dict:
    base: dict[str, object] = dict(
        segment_number=number,
        start_seconds=start,
        end_seconds=end,
        beat_type="setup",
        narrative_intent="Establish the mystery.",
        emotional_intent="Curious.",
        pacing_intent="Moderate.",
        visual_intent="Wide establishing shot.",
        voice_intent="Neutral narrator.",
        music_intent="music.mystery_ambient.",
        sfx_intent="Genre-default.",
        editing_intent="Standard cut.",
        transition_intent="Cut in, cut out.",
    )
    base.update(overrides)
    return base


def test_valid_gapless_coverage_constructs_successfully() -> None:
    brief = ProductionSemanticBrief(
        script_lock_hash="abc123",
        target_duration_seconds=20,
        segments=[
            ProductionSemanticSegment(**_segment(1, 0.0, 10.0)),
            ProductionSemanticSegment(**_segment(2, 10.0, 20.0)),
        ],
    )

    assert len(brief.segments) == 2


def test_gap_between_segments_is_rejected() -> None:
    with pytest.raises(ValueError, match="gap or overlap"):
        ProductionSemanticBrief(
            script_lock_hash="abc123",
            target_duration_seconds=20,
            segments=[
                ProductionSemanticSegment(**_segment(1, 0.0, 8.0)),
                ProductionSemanticSegment(**_segment(2, 10.0, 20.0)),
            ],
        )


def test_overlap_between_segments_is_rejected() -> None:
    with pytest.raises(ValueError, match="gap or overlap"):
        ProductionSemanticBrief(
            script_lock_hash="abc123",
            target_duration_seconds=20,
            segments=[
                ProductionSemanticSegment(**_segment(1, 0.0, 12.0)),
                ProductionSemanticSegment(**_segment(2, 10.0, 20.0)),
            ],
        )


def test_first_segment_must_start_at_zero() -> None:
    with pytest.raises(ValueError, match="must start at 0"):
        ProductionSemanticBrief(
            script_lock_hash="abc123",
            target_duration_seconds=20,
            segments=[ProductionSemanticSegment(**_segment(1, 1.0, 20.0))],
        )


def test_content_hash_is_stable_for_identical_input() -> None:
    segments = [
        ProductionSemanticSegment(**_segment(1, 0.0, 10.0)),
        ProductionSemanticSegment(**_segment(2, 10.0, 20.0)),
    ]
    brief_a = ProductionSemanticBrief(
        script_lock_hash="abc123", target_duration_seconds=20, segments=segments
    )
    brief_b = ProductionSemanticBrief(
        script_lock_hash="abc123", target_duration_seconds=20, segments=list(segments)
    )

    assert brief_a.content_hash == brief_b.content_hash


def test_content_hash_changes_when_intent_changes() -> None:
    brief_a = ProductionSemanticBrief(
        script_lock_hash="abc123",
        target_duration_seconds=10,
        segments=[ProductionSemanticSegment(**_segment(1, 0.0, 10.0))],
    )
    brief_b = ProductionSemanticBrief(
        script_lock_hash="abc123",
        target_duration_seconds=10,
        segments=[
            ProductionSemanticSegment(
                **_segment(1, 0.0, 10.0, visual_intent="Close-up shot.")
            )
        ],
    )

    assert brief_a.content_hash != brief_b.content_hash


def test_reveal_protected_and_curiosity_loop_default_to_unset() -> None:
    segment = ProductionSemanticSegment(**_segment(1, 0.0, 10.0))

    assert segment.reveal_protected is False
    assert segment.related_curiosity_loop is None
    assert segment.beat_id is None
    assert segment.supporting_claims == []
