from __future__ import annotations

import pytest

from src.models.audio_cue_policy import AudioCueConflictType
from src.models.audio_track import AudioTrack, AudioTrackType
from src.services.audio_cue_policy_service import AudioCuePolicyService


def _sfx_track(
    *, start: float, preset_id: str = "sfx.whoosh", volume: float = 0.7
) -> AudioTrack:
    return AudioTrack(
        track_type=AudioTrackType.SOUND_EFFECT,
        source_file=f"/tmp/{preset_id}.mp3",
        start_time_seconds=start,
        duration_seconds=1.0,
        volume=volume,
        metadata={"resolved_preset_id": preset_id},
    )


def _music_track(*, start: float, duration: float, volume: float) -> AudioTrack:
    return AudioTrack(
        track_type=AudioTrackType.BACKGROUND_MUSIC,
        source_file="/tmp/music.mp3",
        start_time_seconds=start,
        duration_seconds=duration,
        volume=volume,
    )


def test_no_conflicts_for_well_spaced_distinct_cues() -> None:
    service = AudioCuePolicyService()

    result = service.evaluate(
        [
            _sfx_track(start=0.0, preset_id="sfx.whoosh"),
            _sfx_track(start=30.0, preset_id="sfx.thud"),
        ]
    )

    assert result.is_clean is True


def test_repetitive_sfx_detected_within_window() -> None:
    service = AudioCuePolicyService(repetition_window_seconds=3.0)

    result = service.evaluate(
        [
            _sfx_track(start=10.0, preset_id="sfx.whoosh"),
            _sfx_track(start=11.5, preset_id="sfx.whoosh"),
        ]
    )

    assert result.is_clean is False
    assert result.conflicts[0].conflict_type == AudioCueConflictType.REPETITIVE_SFX


def test_same_preset_outside_window_is_not_flagged() -> None:
    service = AudioCuePolicyService(repetition_window_seconds=3.0)

    result = service.evaluate(
        [
            _sfx_track(start=10.0, preset_id="sfx.whoosh"),
            _sfx_track(start=60.0, preset_id="sfx.whoosh"),
        ]
    )

    assert result.is_clean is True


def test_different_presets_close_together_are_not_flagged() -> None:
    service = AudioCuePolicyService(repetition_window_seconds=3.0)

    result = service.evaluate(
        [
            _sfx_track(start=10.0, preset_id="sfx.whoosh"),
            _sfx_track(start=10.5, preset_id="sfx.thud"),
        ]
    )

    assert result.is_clean is True


def test_loudness_accumulation_detected_for_overlapping_loud_tracks() -> None:
    service = AudioCuePolicyService(loudness_ceiling=1.0)

    result = service.evaluate(
        [
            _music_track(start=0.0, duration=10.0, volume=0.7),
            _sfx_track(start=5.0, preset_id="sfx.whoosh", volume=0.6),
        ]
    )

    assert result.is_clean is False
    assert (
        result.conflicts[0].conflict_type == AudioCueConflictType.LOUDNESS_ACCUMULATION
    )


def test_non_overlapping_loud_tracks_are_not_flagged() -> None:
    service = AudioCuePolicyService(loudness_ceiling=1.0)

    result = service.evaluate(
        [
            _music_track(start=0.0, duration=5.0, volume=0.9),
            _sfx_track(start=10.0, preset_id="sfx.whoosh", volume=0.9),
        ]
    )

    assert result.is_clean is True


def test_constructor_rejects_negative_repetition_window() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        AudioCuePolicyService(repetition_window_seconds=-1.0)


def test_constructor_rejects_non_positive_loudness_ceiling() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        AudioCuePolicyService(loudness_ceiling=0.0)


def test_empty_tracks_are_clean() -> None:
    service = AudioCuePolicyService()

    result = service.evaluate([])

    assert result.is_clean is True
