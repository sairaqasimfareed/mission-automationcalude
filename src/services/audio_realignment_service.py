from __future__ import annotations

from collections.abc import Iterable

from src.models.audio_timeline import AudioTimeline
from src.models.audio_track import AudioTrack, AudioTrackType
from src.models.render_result import SceneRenderTiming
from src.models.sound_design_plan import SoundDesignPlan
from src.models.video_timeline import VideoTimeline

# Which time axis a track's start_time_seconds was computed against. Stored in
# AudioTrack.metadata so a track is corrected exactly once and tracks that were
# already placed in real time are never touched.
POSITION_BASIS_KEY = "position_basis"

# Voice laid end to end from its real lengths, before any video existed.
BASIS_SEQUENTIAL = "sequential"

# Positions read off the video timeline's nominal item starts, which ignore
# that every crossfade makes the real video shorter.
BASIS_NOMINAL = "nominal"

# Already in real, crossfade-corrected video time (also what the render's own
# voice / sound-effect / music steps produce) - never adjusted again.
BASIS_REAL = "real"

_CONTIGUITY_TOLERANCE_SECONDS = 0.02


def mark_position_basis(track: AudioTrack, basis: str) -> None:
    track.metadata[POSITION_BASIS_KEY] = basis


def realign_audio_to_scene_timings(
    audio_timeline: AudioTimeline,
    *,
    video_timeline: VideoTimeline,
    scene_timings: Iterable[SceneRenderTiming],
    sound_design_plan: SoundDesignPlan | None = None,
) -> int:
    """
    Move audio generated from the Audio tab onto the video's REAL scene timing.

    Real-world finding, 2026-10-03: the Audio tab places voice end to end from
    its real lengths (no video exists yet, so nothing else is possible), and
    reads sound-effect/music positions off the video timeline's nominal item
    starts. Both ignore that every crossfade shortens the real video and that
    clips are rounded. The render then used those stored positions as they
    were: on a real 18-scene project the voice ended up 11s behind the picture
    (Muse) or 9s ahead of it (Flow) by the last scene, while subtitles - timed
    from the real scene starts - stayed correct. The render's own voice/SFX/music
    steps correct for this when they generate; the Audio-tab path never did.

    scene_timings are each scene's real start/end in the encoded video (the
    video-only render's own scene_timings, or the same computation). Only tracks
    whose position basis says they need it are moved - flagged "sequential" /
    "nominal" - plus voice tracks with no flag at all that are exactly end to
    end (a voiceover generated before the flag existed). Each is moved once and
    marked "real", so calling this again, or on tracks the render made itself,
    changes nothing. A scene missing from the timings leaves its track alone.

    Returns the number of tracks moved.
    """

    real = {
        timing.scene_number: (timing.start_seconds, timing.end_seconds)
        for timing in reversed(list(scene_timings))
    }

    if not real:
        return 0

    nominal = _nominal_scene_spans(video_timeline)
    moved = 0

    voice_tracks = [
        track
        for track in audio_timeline.tracks
        if track.track_type == AudioTrackType.VOICEOVER
        and _scene_number(track) is not None
    ]
    unflagged_voice_is_sequential = _is_contiguous(voice_tracks)

    for track in audio_timeline.tracks:
        basis = track.metadata.get(POSITION_BASIS_KEY)

        if basis == BASIS_REAL:
            continue

        if track.track_type == AudioTrackType.VOICEOVER:
            scene_number = _scene_number(track)

            needs_move = basis == BASIS_SEQUENTIAL or (
                basis is None and unflagged_voice_is_sequential
            )

            if scene_number in real and needs_move:
                moved += _move(track, start=real[scene_number][0])

        elif track.track_type == AudioTrackType.SOUND_EFFECT and basis == BASIS_NOMINAL:
            scene_number = _scene_number(track)

            if scene_number in real and scene_number in nominal:
                real_start, real_end = real[scene_number]
                offset = max(0.0, track.start_time_seconds - nominal[scene_number][0])
                offset = min(offset, max(0.0, real_end - real_start))
                moved += _move(track, start=real_start + offset)

        elif (
            track.track_type == AudioTrackType.BACKGROUND_MUSIC
            and basis == BASIS_NOMINAL
            and sound_design_plan is not None
        ):
            segment = next(
                (
                    item
                    for item in sound_design_plan.music_segments
                    if str(item.id) == track.metadata.get("sound_design_segment_id")
                ),
                None,
            )

            if (
                segment is not None
                and segment.start_scene_number in real
                and segment.end_scene_number in real
            ):
                start = real[segment.start_scene_number][0]
                span = real[segment.end_scene_number][1] - start

                if span > 0:
                    moved += _move(track, start=start, duration=span)

    return moved


def _move(track: AudioTrack, *, start: float, duration: float | None = None) -> int:
    changed = abs(track.start_time_seconds - start) > 1e-6

    if duration is not None and abs(track.duration_seconds - duration) > 1e-6:
        track.duration_seconds = duration
        changed = True

    track.start_time_seconds = start
    mark_position_basis(track, BASIS_REAL)

    return 1 if changed else 0


def _scene_number(track: AudioTrack) -> int | None:
    value = track.metadata.get("scene_number")

    if isinstance(value, bool) or not isinstance(value, int):
        return None

    return value


def _is_contiguous(voice_tracks: list[AudioTrack]) -> bool:
    """True when the voice tracks, in scene order, run exactly end to end from 0."""

    if not voice_tracks:
        return False

    ordered = sorted(voice_tracks, key=lambda track: _scene_number(track) or 0)

    if abs(ordered[0].start_time_seconds) > _CONTIGUITY_TOLERANCE_SECONDS:
        return False

    for previous, current in zip(ordered, ordered[1:], strict=False):
        expected = previous.start_time_seconds + previous.duration_seconds

        if abs(current.start_time_seconds - expected) > _CONTIGUITY_TOLERANCE_SECONDS:
            return False

    return True


def _nominal_scene_spans(
    video_timeline: VideoTimeline,
) -> dict[int, tuple[float, float]]:
    spans: dict[int, tuple[float, float]] = {}

    for item in video_timeline.items:
        if not item.enabled:
            continue

        start, end = spans.get(
            item.scene_number, (item.start_time_seconds, item.end_time_seconds)
        )
        spans[item.scene_number] = (
            min(start, item.start_time_seconds),
            max(end, item.end_time_seconds),
        )

    return spans
