"""Project pace (Relaxed / Normal / Fast): the pause after each line and the voice speed."""

from __future__ import annotations

from src.models.project_pace import ProjectPace
from src.models.video_job import VideoJob
from src.services.scene_hold import hold_seconds
from src.services.voice_cast_service import _paced_speed


def _job(genre: str = "genre.mystery") -> VideoJob:
    return VideoJob(
        project_name="P",
        channel_name="C",
        niche="n",
        topic="t",
        genre_id=genre,
    )


def test_normal_pace_changes_nothing() -> None:
    job = _job()

    assert job.pace == ProjectPace.NORMAL
    assert hold_seconds(job) == 1.0  # mystery's own pause
    assert _paced_speed(1.0, job) == 1.0


def test_relaxed_pace_lengthens_the_genres_pause_and_slows_the_voice() -> None:
    job = _job()
    job.pace = ProjectPace.RELAXED

    assert hold_seconds(job) == 1.6
    assert _paced_speed(1.0, job) < 1.0


def test_fast_pace_shortens_the_pause_but_never_below_zero() -> None:
    job = _job("genre.default")
    job.pace = ProjectPace.FAST

    assert hold_seconds(job) == 0.0
    assert _paced_speed(1.0, job) > 1.0


def test_an_operator_chosen_pause_is_never_changed_by_the_pace() -> None:
    job = _job()
    job.scene_hold_seconds = 0.4
    job.pace = ProjectPace.RELAXED

    assert hold_seconds(job) == 0.4


def test_voice_speed_stays_inside_what_elevenlabs_accepts() -> None:
    job = _job()
    job.pace = ProjectPace.FAST

    assert _paced_speed(1.2, job) == 1.2
    job.pace = ProjectPace.RELAXED
    assert _paced_speed(0.7, job) == 0.7
