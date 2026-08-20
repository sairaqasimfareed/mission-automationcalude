from __future__ import annotations

import pytest

from src.models.audio_timeline import AudioTimeline
from src.models.audio_track import AudioTrack, AudioTrackType
from src.models.enums import ProductionMode
from src.models.media_strategy import SceneSourceType
from src.models.video_clip import VideoClip
from src.models.video_job import VideoJob
from src.models.video_timeline import VideoTimeline
from src.models.video_timeline_item import VideoTimelineItem
from src.services.render_identity_service import RenderIdentityService


def _job(**overrides: object) -> VideoJob:
    job = VideoJob(
        project_name="Test Project",
        channel_name="Test Channel",
        niche="test niche",
        topic="Test topic",
    )

    # Mutate after construction rather than passing every field through
    # the constructor - VideoJob's cross-field validators (e.g. "video
    # clips cannot exist without planned scenes") only run on
    # construction, not on attribute assignment, so this sidesteps
    # having to build a full valid upstream chain for tests that only
    # care about the render-identity-relevant fields.
    for field_name, value in overrides.items():
        setattr(job, field_name, value)

    return job


def _clip(number: int = 1, local_file: str = "clip.mp4") -> VideoClip:
    return VideoClip(
        scene_number=number,
        source_type=SceneSourceType.MANUAL_UPLOAD,
        duration_seconds=5,
        local_file=local_file,
    )


def _video_timeline(*, local_file: str = "clip.mp4") -> VideoTimeline:
    return VideoTimeline(
        items=[
            VideoTimelineItem(
                clip=_clip(1, local_file=local_file),
                scene_number=1,
                start_time_seconds=0.0,
                end_time_seconds=5.0,
                track_index=0,
            )
        ],
        output_resolution="1920x1080",
        frame_rate=30,
    )


def _audio_timeline(*, volume: float = 1.0) -> AudioTimeline:
    return AudioTimeline(
        tracks=[
            AudioTrack(
                track_type=AudioTrackType.VOICEOVER,
                source_file="voice.mp3",
                start_time_seconds=0.0,
                duration_seconds=5.0,
                volume=volume,
            )
        ]
    )


def test_compute_requires_a_video_timeline() -> None:
    job = _job(audio_timeline=_audio_timeline())

    with pytest.raises(ValueError, match="requires a built video timeline"):
        RenderIdentityService().compute(job)


def test_compute_requires_an_audio_timeline() -> None:
    job = _job(
        video_clips=[_clip()],
        video_timeline=_video_timeline(),
    )

    with pytest.raises(ValueError, match="requires an audio timeline"):
        RenderIdentityService().compute(job)


def test_compute_is_deterministic_for_identical_inputs() -> None:
    job_a = _job(
        video_clips=[_clip()],
        video_timeline=_video_timeline(),
        audio_timeline=_audio_timeline(),
    )
    job_b = _job(
        video_clips=[_clip()],
        video_timeline=_video_timeline(),
        audio_timeline=_audio_timeline(),
    )

    service = RenderIdentityService()

    assert service.compute(job_a) == service.compute(job_b)


def test_compute_is_a_64_character_hex_sha256() -> None:
    job = _job(
        video_clips=[_clip()],
        video_timeline=_video_timeline(),
        audio_timeline=_audio_timeline(),
    )

    identity = RenderIdentityService().compute(job)

    assert len(identity) == 64
    assert all(char in "0123456789abcdef" for char in identity)


def test_compute_changes_when_the_clip_source_changes() -> None:
    job_a = _job(
        video_clips=[_clip(local_file="clip_a.mp4")],
        video_timeline=_video_timeline(local_file="clip_a.mp4"),
        audio_timeline=_audio_timeline(),
    )
    job_b = _job(
        video_clips=[_clip(local_file="clip_b.mp4")],
        video_timeline=_video_timeline(local_file="clip_b.mp4"),
        audio_timeline=_audio_timeline(),
    )

    service = RenderIdentityService()

    assert service.compute(job_a) != service.compute(job_b)


def test_compute_changes_when_audio_volume_changes() -> None:
    job_a = _job(
        video_clips=[_clip()],
        video_timeline=_video_timeline(),
        audio_timeline=_audio_timeline(volume=1.0),
    )
    job_b = _job(
        video_clips=[_clip()],
        video_timeline=_video_timeline(),
        audio_timeline=_audio_timeline(volume=0.5),
    )

    service = RenderIdentityService()

    assert service.compute(job_a) != service.compute(job_b)


def test_compute_changes_when_production_mode_changes() -> None:
    job_a = _job(
        video_clips=[_clip()],
        video_timeline=_video_timeline(),
        audio_timeline=_audio_timeline(),
        production_mode=ProductionMode.PREMIUM,
    )
    job_b = _job(
        video_clips=[_clip()],
        video_timeline=_video_timeline(),
        audio_timeline=_audio_timeline(),
        production_mode=ProductionMode.QUICK,
    )

    service = RenderIdentityService()

    assert service.compute(job_a) != service.compute(job_b)


def test_compute_is_order_independent_across_tracks() -> None:
    timeline_a = AudioTimeline(
        tracks=[
            AudioTrack(
                track_type=AudioTrackType.VOICEOVER,
                source_file="voice.mp3",
                start_time_seconds=0.0,
                duration_seconds=5.0,
            ),
            AudioTrack(
                track_type=AudioTrackType.BACKGROUND_MUSIC,
                source_file="music.mp3",
                start_time_seconds=0.0,
                duration_seconds=5.0,
            ),
        ]
    )
    timeline_b = AudioTimeline(tracks=list(reversed(timeline_a.tracks)))

    job_a = _job(
        video_clips=[_clip()],
        video_timeline=_video_timeline(),
        audio_timeline=timeline_a,
    )
    job_b = _job(
        video_clips=[_clip()],
        video_timeline=_video_timeline(),
        audio_timeline=timeline_b,
    )

    service = RenderIdentityService()

    assert service.compute(job_a) == service.compute(job_b)
