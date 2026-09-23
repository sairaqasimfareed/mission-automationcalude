"""
REQ-10(a), 2026-09-22: filter_audio_timeline_for_mux is the thin
mux-time filtering layer applied before REQ-00 Stage 2's
AudioMuxRenderService.mux() - generation always runs unconditionally
(see AudioInclusionPreferences' own docstring for why), these toggles
only decide which already-generated tracks actually reach the mux.
"""

from __future__ import annotations

from src.models.audio_inclusion_preferences import AudioInclusionPreferences
from src.models.audio_timeline import AudioTimeline
from src.models.audio_track import AudioTrack, AudioTrackType
from src.services.audio_inclusion_filter_service import (
    filter_audio_timeline_for_mux,
)


def _track(track_type: AudioTrackType) -> AudioTrack:
    return AudioTrack(
        track_type=track_type,
        source_file=f"{track_type.value}.wav",
        start_time_seconds=0.0,
        duration_seconds=1.0,
    )


def _all_track_types_timeline() -> AudioTimeline:
    return AudioTimeline(
        tracks=[
            _track(AudioTrackType.NATIVE_CLIP),
            _track(AudioTrackType.VOICEOVER),
            _track(AudioTrackType.BACKGROUND_MUSIC),
            _track(AudioTrackType.SOUND_EFFECT),
        ]
    )


def test_default_preferences_match_todays_real_behavior() -> None:
    """
    Every existing job (loaded before this field existed) must keep
    exactly today's real behavior - every generated track type
    included, native-clip audio excluded (a new, opt-in capability
    nothing generates yet).
    """

    preferences = AudioInclusionPreferences()

    filtered = filter_audio_timeline_for_mux(
        audio_timeline=_all_track_types_timeline(), preferences=preferences
    )

    types = {track.track_type for track in filtered.tracks}

    assert types == {
        AudioTrackType.VOICEOVER,
        AudioTrackType.BACKGROUND_MUSIC,
        AudioTrackType.SOUND_EFFECT,
    }


def test_all_toggles_off_yields_no_tracks() -> None:
    preferences = AudioInclusionPreferences(
        include_native_clip_audio=False,
        include_voiceover=False,
        include_music=False,
        include_sound_effects=False,
    )

    filtered = filter_audio_timeline_for_mux(
        audio_timeline=_all_track_types_timeline(), preferences=preferences
    )

    assert filtered.tracks == []


def test_each_toggle_independently_controls_its_own_track_type() -> None:
    preferences = AudioInclusionPreferences(
        include_native_clip_audio=True,
        include_voiceover=False,
        include_music=True,
        include_sound_effects=False,
    )

    filtered = filter_audio_timeline_for_mux(
        audio_timeline=_all_track_types_timeline(), preferences=preferences
    )

    types = {track.track_type for track in filtered.tracks}

    assert types == {
        AudioTrackType.NATIVE_CLIP,
        AudioTrackType.BACKGROUND_MUSIC,
    }


def test_filtering_never_mutates_the_original_timeline() -> None:
    original = _all_track_types_timeline()
    original_track_count = len(original.tracks)

    filter_audio_timeline_for_mux(
        audio_timeline=original,
        preferences=AudioInclusionPreferences(
            include_voiceover=False,
            include_music=False,
            include_sound_effects=False,
        ),
    )

    assert len(original.tracks) == original_track_count
