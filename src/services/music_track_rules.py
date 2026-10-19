"""Which background-music tracks stand when a video has both kinds.

"Generate background music" makes ONE track for the whole video; "Generate music pieces" makes one track per planned
mood segment. They answer the same question, so only one kind may play. Found live 2026-10-19 (Joan arc): the whole-video
track was generated first and the five pieces afterwards, nothing removed the first, so the Music card read "6 tracks,
2 m 56 s" for an 88 s video and both kinds played at once. When any piece exists the pieces stand.
"""

from __future__ import annotations

from src.models.audio_timeline import AudioTimeline
from src.models.audio_track import AudioTrackType

SEGMENT_KEY = "sound_design_segment_id"


def drop_superseded_whole_video_music(timeline: AudioTimeline) -> int:
    """Remove the whole-video music track(s) when mood pieces exist. Returns how many were removed."""

    music = [
        track
        for track in timeline.tracks
        if track.track_type == AudioTrackType.BACKGROUND_MUSIC
    ]

    if not any(track.metadata.get(SEGMENT_KEY) for track in music):
        return 0

    superseded = [track for track in music if not track.metadata.get(SEGMENT_KEY)]

    if not superseded:
        return 0

    ids = {id(track) for track in superseded}
    timeline.tracks = [track for track in timeline.tracks if id(track) not in ids]

    return len(superseded)
