"""
Regenerating the sound design plan, 2026-10-03: a plan made during a dry-run
session (placeholder "dry-run sound effect cue..." text) had no way to be
replaced - the pipeline only creates one when none exists.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Callable, Iterator  # noqa: E402
from unittest.mock import MagicMock, patch  # noqa: E402
from uuid import UUID  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from src.desktop.views.production_audio_view import ProductionAudioView  # noqa: E402
from src.models.audio_timeline import AudioTimeline  # noqa: E402
from src.models.audio_track import (  # noqa: E402
    AudioTrack,
    AudioTrackStatus,
    AudioTrackType,
)
from src.models.scene import Scene  # noqa: E402
from src.models.sound_design_plan import (  # noqa: E402
    MusicMoodSegment,
    SoundDesignPlan,
    SoundEffectCueDirective,
)
from src.models.video_job import VideoJob  # noqa: E402

_REGENERATE = "Regenerate sound design plan"
_GENERATE = "Generate sound design plan"


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])

    yield app  # type: ignore[misc]


class _Store:
    def __init__(self, job: VideoJob) -> None:
        self._job = job

    def get(self, job_id: UUID) -> VideoJob | None:
        return self._job if job_id == self._job.id else None


def _scene() -> Scene:
    return Scene(
        scene_number=1,
        title="Scene 1",
        narration="Honey may soothe a cough.",
        visual_prompt="Honey.",
        estimated_duration_seconds=8,
    )


def _track(track_id: str | None = None) -> AudioTrack:
    track = AudioTrack(
        track_type=AudioTrackType.SOUND_EFFECT,
        source_file="effects/knock.mp3",
        duration_seconds=2.0,
        status=AudioTrackStatus.READY,
    )

    return track


def _job_with_dry_run_plan() -> tuple[VideoJob, AudioTrack, AudioTrack]:
    job = VideoJob(
        project_name="Test",
        channel_name="Channel",
        niche="testing",
        topic="A topic",
        genre_id="genre.medical",
    )
    job.scenes = [_scene()]
    sfx_track = _track()
    music_track = AudioTrack(
        track_type=AudioTrackType.BACKGROUND_MUSIC,
        source_file="music/mood.mp3",
        duration_seconds=30.0,
        status=AudioTrackStatus.READY,
    )
    unrelated = AudioTrack(
        track_type=AudioTrackType.VOICEOVER,
        source_file="voice/narration.mp3",
        duration_seconds=20.0,
        status=AudioTrackStatus.READY,
    )
    job.audio_timeline = AudioTimeline(tracks=[sfx_track, music_track, unrelated])
    job.sound_design_plan = SoundDesignPlan(
        sfx_cues=[
            SoundEffectCueDirective(
                scene_number=1,
                generation_prompt="dry-run sound effect cue",
                rationale="Dry-run rationale.",
                audio_track_id=str(sfx_track.id),
            )
        ],
        music_segments=[
            MusicMoodSegment(
                start_scene_number=1,
                end_scene_number=1,
                mood_description="dry-run mood description",
                rationale="Dry-run rationale.",
                audio_track_id=str(music_track.id),
            )
        ],
    )

    return job, sfx_track, music_track


def _view(
    job: VideoJob,
    regenerate: Callable[[VideoJob], VideoJob] | None,
    on_change: Callable[[], None] = lambda: None,
) -> ProductionAudioView:
    view = ProductionAudioView(
        job_store=_Store(job),  # type: ignore[arg-type]
        media_generation_pipeline=MagicMock(),
        on_change=on_change,
        regenerate_sound_design_plan=regenerate,
    )
    view.set_job(job.id)
    view.refresh(job)

    return view


def _texts(view: ProductionAudioView) -> list[str]:
    return [b.text() for b in view.findChildren(QPushButton)]


def _new_plan() -> SoundDesignPlan:
    return SoundDesignPlan(
        sfx_cues=[
            SoundEffectCueDirective(
                scene_number=1,
                generation_prompt="a spoon stirring honey into a warm mug",
                rationale="Narration mentions a warm drink.",
            )
        ],
        music_segments=[
            MusicMoodSegment(
                start_scene_number=1,
                end_scene_number=1,
                mood_description="calm, reassuring, warm",
                rationale="Soothing tone.",
            )
        ],
    )


def test_the_button_appears_only_when_regeneration_is_wired(qapp: QApplication) -> None:
    job, _a, _b = _job_with_dry_run_plan()

    assert _REGENERATE in _texts(_view(job, lambda j: j))
    assert _REGENERATE not in _texts(_view(job, None))


def test_clicking_replaces_the_plan_and_refreshes(qapp: QApplication) -> None:
    job, _a, _b = _job_with_dry_run_plan()
    changes: list[bool] = []

    def regenerate(target: VideoJob) -> VideoJob:
        target.sound_design_plan = _new_plan()

        return target

    view = _view(job, regenerate, on_change=lambda: changes.append(True))
    next(b for b in view.findChildren(QPushButton) if b.text() == _REGENERATE).click()

    assert job.sound_design_plan is not None
    assert "honey" in job.sound_design_plan.sfx_cues[0].generation_prompt
    assert changes == [True]


def test_audio_from_the_old_plan_is_dropped_but_other_tracks_stay(
    qapp: QApplication,
) -> None:
    job, sfx_track, music_track = _job_with_dry_run_plan()
    assert job.audio_timeline is not None

    def regenerate(target: VideoJob) -> VideoJob:
        target.sound_design_plan = _new_plan()

        return target

    view = _view(job, regenerate)
    next(b for b in view.findChildren(QPushButton) if b.text() == _REGENERATE).click()

    remaining = {track.track_type for track in job.audio_timeline.tracks}

    # The old plan's effect and music (their items no longer exist) go;
    # the voiceover is untouched.
    assert remaining == {AudioTrackType.VOICEOVER}


def test_a_failed_regeneration_changes_nothing_and_shows_the_error(
    qapp: QApplication,
) -> None:
    job, sfx_track, music_track = _job_with_dry_run_plan()
    assert job.audio_timeline is not None
    old_plan = job.sound_design_plan

    def regenerate(target: VideoJob) -> VideoJob:
        raise RuntimeError("Anthropic API request failed with status 500")

    view = _view(job, regenerate)

    with patch(
        "src.desktop.views.production_audio_view.show_recoverable_error"
    ) as show_error:
        next(
            b for b in view.findChildren(QPushButton) if b.text() == _REGENERATE
        ).click()

    show_error.assert_called_once()
    assert "status 500" in show_error.call_args.args[2]
    assert job.sound_design_plan is old_plan
    assert len(job.audio_timeline.tracks) == 3


def test_a_job_with_scenes_but_no_plan_gets_a_generate_button(
    qapp: QApplication,
) -> None:
    job, _a, _b = _job_with_dry_run_plan()
    job.sound_design_plan = None

    assert _GENERATE in _texts(_view(job, lambda j: j))


def test_no_plan_and_no_scenes_shows_nothing(qapp: QApplication) -> None:
    job, _a, _b = _job_with_dry_run_plan()
    job.sound_design_plan = None
    job.scenes = []

    texts = _texts(_view(job, lambda j: j))

    assert _GENERATE not in texts
    assert _REGENERATE not in texts


def test_no_plan_and_no_wiring_keeps_the_card_absent(qapp: QApplication) -> None:
    """Unchanged behaviour for every caller that never wired regeneration."""

    job, _a, _b = _job_with_dry_run_plan()
    job.sound_design_plan = None

    texts = _texts(_view(job, None))

    assert _GENERATE not in texts
    assert _REGENERATE not in texts
