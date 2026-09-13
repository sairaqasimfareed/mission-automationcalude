from __future__ import annotations

import pytest

from src.models.sound_design_plan import (
    MUSIC_COST_PER_STARTED_MINUTE_USD,
    SOUND_EFFECT_COST_PER_CUE_USD,
    MusicMoodSegment,
    SoundDesignItemStatus,
    SoundEffectCueDirective,
)


def _cue() -> SoundEffectCueDirective:
    return SoundEffectCueDirective(
        scene_number=1,
        generation_prompt="a wooden door creaking slowly",
        rationale="The narration mentions an old door.",
    )


def _segment() -> MusicMoodSegment:
    return MusicMoodSegment(
        start_scene_number=1,
        end_scene_number=3,
        mood_description="sparse, quiet unease",
        rationale="Opening setup.",
    )


def test_sfx_cue_estimated_cost_matches_real_elevenlabs_rate() -> None:
    assert _cue().estimated_cost_usd == SOUND_EFFECT_COST_PER_CUE_USD


def test_sfx_cue_defaults_to_pending_status() -> None:
    assert _cue().status == SoundDesignItemStatus.PENDING


def test_sfx_cue_rejects_empty_prompt() -> None:
    with pytest.raises(ValueError):
        SoundEffectCueDirective(
            scene_number=1,
            generation_prompt="   ",
            rationale="Some rationale.",
        )


def test_music_segment_rejects_end_before_start() -> None:
    with pytest.raises(ValueError):
        MusicMoodSegment(
            start_scene_number=5,
            end_scene_number=2,
            mood_description="tense",
            rationale="Should fail.",
        )


def test_music_segment_cost_rounds_up_to_started_minute() -> None:
    segment = _segment()

    # 61 seconds must bill as 2 started minutes, not 1.017 minutes.
    assert segment.estimated_cost_usd(segment_duration_seconds=61.0) == pytest.approx(
        2 * MUSIC_COST_PER_STARTED_MINUTE_USD
    )


def test_music_segment_cost_for_exactly_one_minute() -> None:
    segment = _segment()

    assert segment.estimated_cost_usd(segment_duration_seconds=60.0) == pytest.approx(
        MUSIC_COST_PER_STARTED_MINUTE_USD
    )


def test_music_segment_cost_for_short_clip_still_bills_one_minute() -> None:
    segment = _segment()

    assert segment.estimated_cost_usd(segment_duration_seconds=8.0) == pytest.approx(
        MUSIC_COST_PER_STARTED_MINUTE_USD
    )


def test_music_segment_cost_zero_for_zero_duration() -> None:
    segment = _segment()

    assert segment.estimated_cost_usd(segment_duration_seconds=0.0) == 0.0
