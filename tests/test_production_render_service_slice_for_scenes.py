from __future__ import annotations

from src.models.audio_timeline import AudioTimeline
from src.models.audio_track import (
    AudioTrack,
    AudioTrackStatus,
    AudioTrackType,
)
from src.models.media_strategy import (
    SceneSourceStatus,
    SceneSourceType,
)
from src.models.video_clip import VideoClip
from src.models.video_timeline import VideoTimeline
from src.models.video_timeline_item import VideoTimelineItem
from src.services.production_render_service import ProductionRenderService

# Mirrors the real job that surfaced the chunk-boundary freeze: four
# scenes split into two chunks of two scenes each, a 1.0s transition
# duration (a round number standing in for a real per-genre value
# like genre.history's 0.6s), each scene's own voiceover positioned
# exactly the way VoicePipelineStage positions it - nominal offset
# minus transition_duration_seconds for every *preceding* scene
# boundary, none of them aware that the boundary between scene 2 and
# scene 3 will become a chunk split (a hard cut, not a real
# crossfade).
_TRANSITION_DURATION_SECONDS = 1.0
_SCENE_DURATION_SECONDS = 4
_TRACK_DURATION_SECONDS = 2.0


def _video_item(scene_number: int) -> VideoTimelineItem:
    start = (scene_number - 1) * _SCENE_DURATION_SECONDS

    clip = VideoClip(
        scene_number=scene_number,
        source_type=SceneSourceType.STOCK_FOOTAGE,
        duration_seconds=_SCENE_DURATION_SECONDS,
        local_file=f"scene_{scene_number}.mp4",
        source_status=SceneSourceStatus.READY,
    )

    return VideoTimelineItem(
        clip=clip,
        scene_number=scene_number,
        start_time_seconds=float(start),
        end_time_seconds=float(start + _SCENE_DURATION_SECONDS),
    )


def _voiceover_track(scene_number: int) -> AudioTrack:
    """
    Build a voiceover track at VoicePipelineStage's own chunk-unaware
    crossfade-corrected position: nominal_offset(scene) -
    transition_duration_seconds * (scene_number - 1).
    """

    nominal_offset = (scene_number - 1) * _SCENE_DURATION_SECONDS

    start = nominal_offset - _TRANSITION_DURATION_SECONDS * (scene_number - 1)

    return AudioTrack(
        track_type=AudioTrackType.VOICEOVER,
        source_file=f"voice_{scene_number}.mp3",
        start_time_seconds=start,
        duration_seconds=_TRACK_DURATION_SECONDS,
        status=AudioTrackStatus.READY,
        metadata={"scene_number": scene_number},
    )


def _video_timeline(scene_count: int) -> VideoTimeline:
    return VideoTimeline(
        items=[_video_item(number) for number in range(1, scene_count + 1)]
    )


def _audio_timeline(
    scene_count: int,
    *,
    extra_tracks: list[AudioTrack] | None = None,
) -> AudioTimeline:
    tracks = [_voiceover_track(number) for number in range(1, scene_count + 1)]

    tracks.extend(extra_tracks or [])

    return AudioTimeline(tracks=tracks)


def _four_scene_video_timeline() -> VideoTimeline:
    return _video_timeline(4)


def _four_scene_audio_timeline(
    *,
    extra_tracks: list[AudioTrack] | None = None,
) -> AudioTimeline:
    return _audio_timeline(4, extra_tracks=extra_tracks)


def _voiceover_starts(tracks: list[AudioTrack]) -> dict[int, float]:
    return {
        int(track.metadata["scene_number"]): track.start_time_seconds
        for track in tracks
        if track.track_type == AudioTrackType.VOICEOVER
    }


def test_boundary_scene_voiceover_is_excluded_from_the_earlier_chunk() -> None:
    """
    Scene 3's voice, per VoicePipelineStage's chunk-unaware formula,
    is stored at t=6.0 (nominal 8.0 minus one transition_duration too
    many). Without the fix, chunk 0's nominal window [0, 8) would
    swallow it whole - the real freeze this test guards against.
    """

    video_timeline = _four_scene_video_timeline()
    audio_timeline = _four_scene_audio_timeline()

    scene_groups = [{1, 2}, {3, 4}]
    scene_chunk_indices = ProductionRenderService._scene_chunk_indices(scene_groups)

    _chunk_video, chunk_audio, _blueprints = ProductionRenderService._slice_for_scenes(
        video_timeline=video_timeline,
        audio_timeline=audio_timeline,
        voice_blueprints=[],
        scene_numbers={1, 2},
        chunk_index=0,
        transition_duration_seconds=_TRANSITION_DURATION_SECONDS,
        scene_chunk_indices=scene_chunk_indices,
    )

    included_scenes = set(_voiceover_starts(chunk_audio.tracks))

    assert included_scenes == {1, 2}


def test_boundary_scene_voiceover_lands_at_local_zero_in_its_own_chunk() -> None:
    """
    Scene 3 starts its own chunk (chunk 1) right where that chunk's
    video begins - a hard cut, no crossfade eating into it - so its
    voiceover must rebase to exactly local t=0, not some fraction of
    a transition_duration off (the arithmetic error an earlier,
    incorrect version of this fix produced: dropping the track from
    every chunk instead of correctly placing it in its own).
    """

    video_timeline = _four_scene_video_timeline()
    audio_timeline = _four_scene_audio_timeline()

    scene_groups = [{1, 2}, {3, 4}]
    scene_chunk_indices = ProductionRenderService._scene_chunk_indices(scene_groups)

    _chunk_video, chunk_audio, _blueprints = ProductionRenderService._slice_for_scenes(
        video_timeline=video_timeline,
        audio_timeline=audio_timeline,
        voice_blueprints=[],
        scene_numbers={3, 4},
        chunk_index=1,
        transition_duration_seconds=_TRANSITION_DURATION_SECONDS,
        scene_chunk_indices=scene_chunk_indices,
    )

    starts = _voiceover_starts(chunk_audio.tracks)

    assert starts == {3: 0.0, 4: 3.0}


def test_every_voiceover_track_appears_in_exactly_one_chunk() -> None:
    """
    The real bug's other failure mode: a naive fix that only adds
    the correction back for the chunk a track truly belongs to (and
    tests it against that chunk's own nominal, uncorrected window)
    can make the same track match *both* chunks' overlap tests -
    duplicated audio at the seam instead of dropped. Every scene's
    voice must appear in exactly one chunk's slice.
    """

    video_timeline = _four_scene_video_timeline()
    audio_timeline = _four_scene_audio_timeline()

    scene_groups = [{1, 2}, {3, 4}]
    scene_chunk_indices = ProductionRenderService._scene_chunk_indices(scene_groups)

    all_included_scenes: list[int] = []

    for chunk_index, group in enumerate(scene_groups):
        _chunk_video, chunk_audio, _blueprints = (
            ProductionRenderService._slice_for_scenes(
                video_timeline=video_timeline,
                audio_timeline=audio_timeline,
                voice_blueprints=[],
                scene_numbers=group,
                chunk_index=chunk_index,
                transition_duration_seconds=_TRANSITION_DURATION_SECONDS,
                scene_chunk_indices=scene_chunk_indices,
            )
        )

        all_included_scenes.extend(_voiceover_starts(chunk_audio.tracks))

    assert sorted(all_included_scenes) == [1, 2, 3, 4]


def test_three_chunks_fix_generalizes_past_two() -> None:
    """
    The fix must not be a two-chunk special case: it has to hold for
    however many chunks a given job's own command length actually
    needs, decided fresh per render by _determine_chunk_count. Six
    scenes split into three two-scene chunks exercises the case two
    chunks alone cannot: a *middle* chunk with a real chunk boundary
    on both sides, where the correction must simultaneously keep an
    earlier scene from bleeding forward into it and a later scene
    from bleeding backward into it, while still placing the chunk's
    own first scene at exactly local t=0 on both sides of the seam.
    """

    video_timeline = _video_timeline(6)
    audio_timeline = _audio_timeline(6)

    scene_groups = [{1, 2}, {3, 4}, {5, 6}]
    scene_chunk_indices = ProductionRenderService._scene_chunk_indices(scene_groups)

    chunk_starts: list[dict[int, float]] = []

    for chunk_index, group in enumerate(scene_groups):
        _chunk_video, chunk_audio, _blueprints = (
            ProductionRenderService._slice_for_scenes(
                video_timeline=video_timeline,
                audio_timeline=audio_timeline,
                voice_blueprints=[],
                scene_numbers=group,
                chunk_index=chunk_index,
                transition_duration_seconds=_TRANSITION_DURATION_SECONDS,
                scene_chunk_indices=scene_chunk_indices,
            )
        )

        chunk_starts.append(_voiceover_starts(chunk_audio.tracks))

    # Every scene appears in exactly one chunk, at exactly the
    # position it should - including the middle chunk's own first
    # scene (5) landing at local zero despite having a real chunk
    # boundary immediately behind it too.
    assert chunk_starts == [
        {1: 0.0, 2: 3.0},
        {3: 0.0, 4: 3.0},
        {5: 0.0, 6: 3.0},
    ]


def test_fix_holds_at_the_real_maximum_chunk_count() -> None:
    """
    ProductionRenderService caps chunking at _MAXIMUM_RENDER_CHUNKS
    (40, see the class constant) - a very long or very densely-scened
    job could genuinely need that many. The correction's own math has
    no chunk-count-specific term anywhere (see _slice_for_scenes'
    docstring: it's built from chunk_index and a scene_chunk_indices
    map, both computed fresh from whatever grouping this job actually
    produced), so nothing here is expected to break as chunk count
    grows - this proves it at the real configured ceiling rather than
    just asserting it, covering every earlier chunk count too since
    each one is a strict subset of this same shape.
    """

    chunk_count = ProductionRenderService._MAXIMUM_RENDER_CHUNKS

    scene_count = chunk_count * 2

    video_timeline = _video_timeline(scene_count)
    audio_timeline = _audio_timeline(scene_count)

    scene_groups = [{2 * index + 1, 2 * index + 2} for index in range(chunk_count)]

    scene_chunk_indices = ProductionRenderService._scene_chunk_indices(scene_groups)

    all_included_scenes: list[int] = []

    for chunk_index, group in enumerate(scene_groups):
        _chunk_video, chunk_audio, _blueprints = (
            ProductionRenderService._slice_for_scenes(
                video_timeline=video_timeline,
                audio_timeline=audio_timeline,
                voice_blueprints=[],
                scene_numbers=group,
                chunk_index=chunk_index,
                transition_duration_seconds=_TRANSITION_DURATION_SECONDS,
                scene_chunk_indices=scene_chunk_indices,
            )
        )

        starts = _voiceover_starts(chunk_audio.tracks)

        first_scene_number = min(group)

        second_scene_number = max(group)

        # Every chunk's own first scene lands at exactly local zero,
        # regardless of how many real chunk boundaries precede it.
        assert starts[first_scene_number] == 0.0

        # The second scene keeps the normal one-real-crossfade-early
        # offset from a plain nominal position (matches every earlier
        # test's 3.0 for a 4.0-nominal-offset, 1.0s-transition pair).
        assert starts[second_scene_number] == 3.0

        all_included_scenes.extend(starts)

    assert sorted(all_included_scenes) == list(range(1, scene_count + 1))


def test_music_track_position_gets_the_same_correction_voiceover_does() -> None:
    """
    Real-world finding, 2026-09-18: music/SFX tracks used to be
    positioned straight from each scene's own nominal
    VideoTimelineItem boundary, never through VoicePipelineStage's
    crossfade-aware formula - confirmed WRONG against a real job
    (MusicPipelineStage/SoundEffectPipelineStage now both compute
    their own real, crossfade-corrected position upstream, exactly
    like voice always has). A scene-3 music segment is therefore built
    here the same way _voiceover_track(3) is - nominal 8.0 minus one
    transition_duration_seconds too many - and must land at exactly
    the same place a scene-3 voiceover track does (see
    test_boundary_scene_voiceover_lands_at_local_zero_in_its_own_chunk):
    local t=0 in its own chunk, not a fraction of a transition off.
    """

    music_track = AudioTrack(
        track_type=AudioTrackType.BACKGROUND_MUSIC,
        source_file="music_scene3.mp3",
        start_time_seconds=6.0,
        duration_seconds=4.0,
        status=AudioTrackStatus.READY,
        metadata={"scene_number": 3},
    )

    video_timeline = _four_scene_video_timeline()
    audio_timeline = _four_scene_audio_timeline(extra_tracks=[music_track])

    scene_groups = [{1, 2}, {3, 4}]
    scene_chunk_indices = ProductionRenderService._scene_chunk_indices(scene_groups)

    _chunk_video, chunk0_audio, _blueprints = ProductionRenderService._slice_for_scenes(
        video_timeline=video_timeline,
        audio_timeline=audio_timeline,
        voice_blueprints=[],
        scene_numbers={1, 2},
        chunk_index=0,
        transition_duration_seconds=_TRANSITION_DURATION_SECONDS,
        scene_chunk_indices=scene_chunk_indices,
    )

    _chunk_video, chunk1_audio, _blueprints = ProductionRenderService._slice_for_scenes(
        video_timeline=video_timeline,
        audio_timeline=audio_timeline,
        voice_blueprints=[],
        scene_numbers={3, 4},
        chunk_index=1,
        transition_duration_seconds=_TRANSITION_DURATION_SECONDS,
        scene_chunk_indices=scene_chunk_indices,
    )

    chunk0_music = [
        track
        for track in chunk0_audio.tracks
        if track.track_type == AudioTrackType.BACKGROUND_MUSIC
    ]

    chunk1_music = [
        track
        for track in chunk1_audio.tracks
        if track.track_type == AudioTrackType.BACKGROUND_MUSIC
    ]

    assert chunk0_music == []

    assert len(chunk1_music) == 1

    # scene 3 starts its own chunk (chunk 1) right where that chunk's
    # video begins - a hard cut, no crossfade eating into it - so the
    # music segment rebases to exactly local t=0, same as voiceover.
    assert chunk1_music[0].start_time_seconds == 0.0

    assert chunk1_music[0].duration_seconds == 4.0


def test_music_track_extending_past_the_chunks_real_video_is_trimmed() -> None:
    """
    The real bug this guards against: a music/SFX track positioned at
    its own correct nominal scene boundary can still extend past the
    *chunk's own real, crossfade-shortened video length* - confirmed
    directly on a real render, where a chunk's own video measured
    51.2s but its own audio (driven by exactly this kind of track)
    measured 56.0s, and the concat step held the last frame for the
    whole 4.8s gap. Such a track must be trimmed to the chunk's real
    boundary, not just repositioned.
    """

    music_track = AudioTrack(
        track_type=AudioTrackType.BACKGROUND_MUSIC,
        source_file="music_scene2.mp3",
        start_time_seconds=5.0,
        duration_seconds=3.0,
        status=AudioTrackStatus.READY,
        metadata={"scene_number": 2},
    )

    video_timeline = _four_scene_video_timeline()
    audio_timeline = _four_scene_audio_timeline(extra_tracks=[music_track])

    scene_groups = [{1, 2}, {3, 4}]
    scene_chunk_indices = ProductionRenderService._scene_chunk_indices(scene_groups)

    _chunk_video, chunk0_audio, _blueprints = ProductionRenderService._slice_for_scenes(
        video_timeline=video_timeline,
        audio_timeline=audio_timeline,
        voice_blueprints=[],
        scene_numbers={1, 2},
        chunk_index=0,
        transition_duration_seconds=_TRANSITION_DURATION_SECONDS,
        scene_chunk_indices=scene_chunk_indices,
    )

    chunk0_music = [
        track
        for track in chunk0_audio.tracks
        if track.track_type == AudioTrackType.BACKGROUND_MUSIC
    ]

    assert len(chunk0_music) == 1

    # Nominally [5.0, 8.0], but chunk 0's real window is [0.0, 7.0]
    # (one real crossfade shortens its nominal 8.0 end) - the track
    # must be clipped to real_chunk_end, not left running to 8.0.
    assert chunk0_music[0].start_time_seconds == 5.0

    assert chunk0_music[0].duration_seconds == 2.0


def test_zero_transition_duration_leaves_slicing_unchanged() -> None:
    """
    No genre profile resolved means transition_duration_seconds is
    0.0 everywhere, so VoicePipelineStage would never have applied
    any crossfade correction when building these tracks either -
    every voiceover sits at its own scene's plain nominal offset.
    Slicing with transition_duration_seconds=0.0 must apply no
    correction at all: each scene's voice stays inside its own
    chunk's plain nominal window, matching pre-fix behavior exactly
    when there is nothing to correct.
    """

    video_timeline = _four_scene_video_timeline()

    audio_timeline = AudioTimeline(
        tracks=[
            AudioTrack(
                track_type=AudioTrackType.VOICEOVER,
                source_file=f"voice_{scene_number}.mp3",
                start_time_seconds=float((scene_number - 1) * _SCENE_DURATION_SECONDS),
                duration_seconds=_TRACK_DURATION_SECONDS,
                status=AudioTrackStatus.READY,
                metadata={"scene_number": scene_number},
            )
            for scene_number in range(1, 5)
        ]
    )

    scene_groups = [{1, 2}, {3, 4}]
    scene_chunk_indices = ProductionRenderService._scene_chunk_indices(scene_groups)

    _chunk_video, chunk_audio, _blueprints = ProductionRenderService._slice_for_scenes(
        video_timeline=video_timeline,
        audio_timeline=audio_timeline,
        voice_blueprints=[],
        scene_numbers={1, 2},
        chunk_index=0,
        transition_duration_seconds=0.0,
        scene_chunk_indices=scene_chunk_indices,
    )

    starts = _voiceover_starts(chunk_audio.tracks)

    assert starts == {1: 0.0, 2: 4.0}
