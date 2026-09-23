from __future__ import annotations

from src.models.audio_inclusion_preferences import AudioInclusionPreferences
from src.models.audio_timeline import AudioTimeline


def filter_audio_timeline_for_mux(
    *,
    audio_timeline: AudioTimeline,
    preferences: AudioInclusionPreferences,
) -> AudioTimeline:
    """
    REQ-10(a): return a new AudioTimeline containing only the tracks
    preferences allows into REQ-00 Stage 2's mux.

    Deliberately a plain function, not a method on
    AudioMuxRenderService itself - mux() stays a general "mux
    whatever tracks you hand it" capability with no knowledge of these
    toggles (see AudioMuxRenderService's own docstring); this is the
    thin filtering layer a caller applies before calling mux(), kept
    separate so mux() never needs to change if these toggles'
    semantics ever do.

    Never mutates the AudioTimeline passed in.
    """

    allowed_types = preferences.allowed_track_types()

    filtered_tracks = [
        track for track in audio_timeline.tracks if track.track_type in allowed_types
    ]

    return audio_timeline.model_copy(update={"tracks": filtered_tracks})
