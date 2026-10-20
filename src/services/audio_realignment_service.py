from __future__ import annotations

from collections.abc import Iterable

from src.models.audio_timeline import AudioTimeline
from src.models.audio_track import AudioTrack, AudioTrackType
from src.models.editing_directives import DirectiveTimingMode
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

# The real start of the track's scene at the time the track was placed on it (sound effects only), so
# a later pass can carry the effect along if the scene moved.
PLACED_SCENE_START_KEY = "placed_scene_start"

_CONTIGUITY_TOLERANCE_SECONDS = 0.02


def mark_position_basis(track: AudioTrack, basis: str) -> None:
    track.metadata[POSITION_BASIS_KEY] = basis


def realign_audio_to_scene_timings(
    audio_timeline: AudioTimeline,
    *,
    video_timeline: VideoTimeline,
    scene_timings: Iterable[SceneRenderTiming],
    sound_design_plan: SoundDesignPlan | None = None,
    transition_seconds: float = 0.7,
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
    video-only render's own scene_timings, or the same computation). Voice goes
    onto its scene's current real start EVERY time (a clip regenerated, cut or held
    since an earlier render moves every later scene); music segments are re-spanned
    from the plan; a sound effect keeps its offset inside its scene and moves with
    it. Calling this twice with the same timings changes nothing. A scene missing
    from the timings leaves its tracks alone.

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

    # Where each scene's voice was before this pass: a sound effect that was placed in real time (and so
    # carries no record of its scene's start) is carried along with its scene by the same distance.
    old_voice_start: dict[int, float] = {}

    for track in audio_timeline.tracks:
        number = _scene_number(track)

        if track.track_type == AudioTrackType.VOICEOVER and number is not None:
            old_voice_start.setdefault(number, track.start_time_seconds)

    for track in audio_timeline.tracks:
        basis = track.metadata.get(POSITION_BASIS_KEY)
        scene_number = _scene_number(track)

        if track.track_type == AudioTrackType.VOICEOVER:
            # A voice always starts where its scene starts in the picture. A position marked "real" was real
            # for the clips of THAT render: a clip regenerated, cut or held since then moves every later
            # scene, and the stored voice stayed behind (live, 2026-10-20: voices up to 16 s ahead of the
            # picture). So every render puts the voice on the scene's current real start.
            if scene_number in real:
                moved += _move(track, start=real[scene_number][0])

        elif track.track_type == AudioTrackType.SOUND_EFFECT:
            if scene_number not in real:
                continue

            real_start, real_end = real[scene_number]
            planned = _planned_effect_start(
                track,
                plan=sound_design_plan,
                real=real,
                scene_number=scene_number,
                transition_seconds=transition_seconds,
            )

            if planned is not None:
                # The plan says where in its scene the effect goes (at the start, at 40 %...): measured
                # from the scene's CURRENT real span, whatever an earlier render did with it - a stamp
                # meant for scene 9 stayed under scene 8's voice (live, 2026-10-20).
                moved += _move(track, start=planned, placed_scene_start=real_start)

                continue

            if basis == BASIS_NOMINAL and scene_number in nominal:
                offset = max(0.0, track.start_time_seconds - nominal[scene_number][0])
                offset = min(offset, max(0.0, real_end - real_start))
                moved += _move(
                    track, start=real_start + offset, placed_scene_start=real_start
                )
            elif basis == BASIS_REAL:
                placed = track.metadata.get(PLACED_SCENE_START_KEY)
                old_start = (
                    float(placed)
                    if isinstance(placed, (int, float))
                    else old_voice_start.get(scene_number)
                )

                if old_start is not None:
                    shifted = track.start_time_seconds + (real_start - old_start)
                    shifted = min(max(shifted, real_start), max(real_start, real_end))
                    moved += _move(track, start=shifted, placed_scene_start=real_start)

        elif (
            track.track_type == AudioTrackType.BACKGROUND_MUSIC
            and basis in (BASIS_NOMINAL, BASIS_REAL)
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


def _planned_effect_start(
    track: AudioTrack,
    *,
    plan: SoundDesignPlan | None,
    real: dict[int, tuple[float, float]],
    scene_number: int,
    transition_seconds: float,
) -> float | None:
    """Where the sound-design plan puts this effect on its scene's real span, or None when the track has no
    plan cue (then the offset-keeping rules above apply)."""

    if plan is None:
        return None

    cue_id = track.metadata.get("sound_design_cue_id")
    cue = next((c for c in plan.sfx_cues if str(c.id) == cue_id), None)

    if cue is None:
        return None

    real_start, real_end = real[scene_number]
    duration = max(real_end - real_start, 0.0)
    window_start = transition_seconds if scene_number != min(real) else 0.0
    window_end = (
        max(window_start, duration - transition_seconds)
        if scene_number != max(real)
        else duration
    )

    if cue.relative_position_percent is not None:
        offset = duration * (cue.relative_position_percent / 100.0)
    elif cue.timing_mode == DirectiveTimingMode.SCENE_START:
        offset = window_start
    elif cue.timing_mode == DirectiveTimingMode.SCENE_MIDDLE:
        offset = (window_start + window_end) / 2.0
    elif cue.timing_mode == DirectiveTimingMode.SCENE_END:
        offset = window_end
    else:
        offset = cue.start_offset_seconds

    return real_start + min(max(offset, window_start), window_end)


def _move(
    track: AudioTrack,
    *,
    start: float,
    duration: float | None = None,
    placed_scene_start: float | None = None,
) -> int:
    changed = abs(track.start_time_seconds - start) > 1e-6

    if placed_scene_start is not None:
        track.metadata[PLACED_SCENE_START_KEY] = placed_scene_start

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
