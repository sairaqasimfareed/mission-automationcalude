"""
Found live 2026-10-19 (Joan arc): "Generate background music" (one whole-video track) was pressed first and the five
planned mood pieces afterwards. Nothing removed the first, so the Music card read "6 track(s) ... 2m 56s total" for an
88 s video and both kinds played at once. When any piece exists the pieces stand.
"""

from __future__ import annotations

from src.models.audio_timeline import AudioTimeline
from src.models.audio_track import AudioTrack, AudioTrackStatus, AudioTrackType
from src.services.music_track_rules import (
    SEGMENT_KEY,
    drop_superseded_whole_video_music,
)


def _music(start: float, seconds: float, segment: str | None = None) -> AudioTrack:
    return AudioTrack(
        track_type=AudioTrackType.BACKGROUND_MUSIC,
        source_file=f"music/{start}.mp3",
        start_time_seconds=start,
        duration_seconds=seconds,
        status=AudioTrackStatus.READY,
        metadata={SEGMENT_KEY: segment} if segment else {},
    )


def _voice() -> AudioTrack:
    return AudioTrack(
        track_type=AudioTrackType.VOICEOVER,
        source_file="voice/1.mp3",
        duration_seconds=3.0,
        status=AudioTrackStatus.READY,
        metadata={"scene_number": 1},
    )


def test_a_whole_video_track_is_dropped_when_pieces_exist() -> None:
    timeline = AudioTimeline(
        tracks=[_voice(), _music(0, 88), _music(0, 23, "a"), _music(23, 36, "b")]
    )

    removed = drop_superseded_whole_video_music(timeline)

    assert removed == 1
    music = [
        t for t in timeline.tracks if t.track_type == AudioTrackType.BACKGROUND_MUSIC
    ]
    assert [t.duration_seconds for t in music] == [23, 36]
    assert any(t.track_type == AudioTrackType.VOICEOVER for t in timeline.tracks)


def test_a_whole_video_track_alone_is_kept() -> None:
    timeline = AudioTimeline(tracks=[_music(0, 88)])

    assert drop_superseded_whole_video_music(timeline) == 0
    assert len(timeline.tracks) == 1


def test_pieces_alone_are_kept() -> None:
    timeline = AudioTimeline(tracks=[_music(0, 23, "a"), _music(23, 36, "b")])

    assert drop_superseded_whole_video_music(timeline) == 0
    assert len(timeline.tracks) == 2


def test_generating_a_music_piece_removes_the_earlier_whole_video_track() -> None:
    from src.models.sound_design_plan import MusicMoodSegment, SoundDesignPlan
    from tests.test_media_generation_pipeline import _clip, _job, _pipeline, _scene

    pipeline = _pipeline()
    job = _job(_scene(1), _scene(2), _scene(3))
    job.video_clips = [_clip(1), _clip(2), _clip(3)]
    pipeline.run_voice(job)
    pipeline.run_timeline(job)
    pipeline.run_music(job)  # the whole-video track

    assert job.audio_timeline is not None
    assert [
        t.metadata.get(SEGMENT_KEY)
        for t in job.audio_timeline.tracks
        if t.track_type == AudioTrackType.BACKGROUND_MUSIC
    ] == [None]

    segment = MusicMoodSegment(
        start_scene_number=2,
        end_scene_number=3,
        mood_description="tense, building drone",
        rationale="The reveal.",
    )
    job.sound_design_plan = SoundDesignPlan(music_segments=[segment])
    pipeline.generate_single_music_segment(job, str(segment.id))

    music = [
        t
        for t in job.audio_timeline.tracks
        if t.track_type == AudioTrackType.BACKGROUND_MUSIC
    ]
    assert len(music) == 1
    assert music[0].metadata[SEGMENT_KEY] == str(segment.id)
