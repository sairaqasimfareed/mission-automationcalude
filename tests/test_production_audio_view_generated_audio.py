"""
"Generated audio" card, 2026-10-03: after generating the voiceover nothing on
the Audio tab said it had worked or how long it was. The card shows, for
voiceover / sound effects / music: how many, total length, who made them, and
each file with a Play button.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest.mock import MagicMock, patch  # noqa: E402
from uuid import UUID  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

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
    SoundDesignItemStatus,
    SoundDesignPlan,
    SoundEffectCueDirective,
)
from src.models.video_job import VideoJob  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])

    yield app  # type: ignore[misc]


class _Store:
    def __init__(self, job: VideoJob) -> None:
        self._job = job

    def get(self, job_id: UUID) -> VideoJob | None:
        return self._job if job_id == self._job.id else None


def _scene(number: int) -> Scene:
    return Scene(
        scene_number=number,
        title=f"Scene {number}",
        narration=f"Narration {number}.",
        visual_prompt=f"Visual {number}.",
        estimated_duration_seconds=8,
    )


def _file(tmp_path: Path, name: str) -> str:
    path = tmp_path / name
    path.write_bytes(b"audio")

    return str(path)


def _track(
    track_type: AudioTrackType,
    source: str,
    seconds: float,
    *,
    start: float = 0.0,
    scene_number: int | None = None,
    provider: str | None = "elevenlabs",
) -> AudioTrack:
    return AudioTrack(
        track_type=track_type,
        source_file=source,
        duration_seconds=seconds,
        start_time_seconds=start,
        status=AudioTrackStatus.READY,
        provider=provider,
        metadata={} if scene_number is None else {"scene_number": scene_number},
    )


def _job(tracks: list[AudioTrack], scenes: int = 3) -> VideoJob:
    job = VideoJob(
        project_name="Test",
        channel_name="Channel",
        niche="testing",
        topic="A topic",
    )
    job.scenes = [_scene(n) for n in range(1, scenes + 1)]

    if tracks:
        job.audio_timeline = AudioTimeline(tracks=tracks)

    return job


def _view(job: VideoJob) -> ProductionAudioView:
    view = ProductionAudioView(
        job_store=_Store(job),  # type: ignore[arg-type]
        media_generation_pipeline=MagicMock(),
        on_change=lambda: None,
    )
    view.set_job(job.id)
    view.refresh(job)

    return view


def _texts(view: ProductionAudioView) -> list[str]:
    return [label.text() for label in view.findChildren(QLabel)]


def _play_buttons(view: ProductionAudioView) -> list[QPushButton]:
    return [b for b in view.findChildren(QPushButton) if b.text() == "Play"]


def test_a_generated_voiceover_shows_count_total_provider_and_each_scene(
    qapp: QApplication, tmp_path: Path
) -> None:
    tracks = [
        _track(
            AudioTrackType.VOICEOVER,
            _file(tmp_path, f"v{n}.mp3"),
            seconds,
            start=start,
            scene_number=n,
        )
        for n, seconds, start in ((1, 7.66, 0.0), (2, 1.07, 7.66), (3, 4.0, 8.73))
    ]
    texts = _texts(_view(_job(tracks)))

    assert any(
        "3 of 3 scenes" in t and "12.7s total" in t and "elevenlabs" in t for t in texts
    )
    assert any(t.startswith("Scene 1 · 7.7s · v1.mp3") for t in texts)
    assert any(t.startswith("Scene 2 · 1.1s · v2.mp3") for t in texts)


def test_a_long_total_is_shown_in_minutes(qapp: QApplication, tmp_path: Path) -> None:
    tracks = [
        _track(AudioTrackType.VOICEOVER, _file(tmp_path, "v.mp3"), 85.6, scene_number=1)
    ]

    assert any("1m 26s total" in t for t in _texts(_view(_job(tracks, scenes=1))))


def test_each_real_file_has_a_play_button_that_opens_it(
    qapp: QApplication, tmp_path: Path
) -> None:
    source = _file(tmp_path, "v1.mp3")
    view = _view(
        _job([_track(AudioTrackType.VOICEOVER, source, 3.0, scene_number=1)], scenes=1)
    )

    buttons = _play_buttons(view)
    assert len(buttons) == 1

    with patch(
        "src.desktop.views.production_audio_view.QDesktopServices.openUrl"
    ) as open_url:
        buttons[0].click()

    open_url.assert_called_once()
    assert Path(open_url.call_args.args[0].toLocalFile()).name == "v1.mp3"


def test_a_placeholder_file_is_labelled_and_has_no_play_button(
    qapp: QApplication,
) -> None:
    view = _view(
        _job(
            [
                _track(
                    AudioTrackType.VOICEOVER,
                    "dry-run://voice/neutral.mp3",
                    8.0,
                    scene_number=1,
                )
            ],
            scenes=1,
        )
    )

    assert any("placeholder" in t for t in _texts(view))
    assert not _play_buttons(view)


def test_a_missing_file_is_labelled_and_has_no_play_button(
    qapp: QApplication, tmp_path: Path
) -> None:
    view = _view(
        _job(
            [
                _track(
                    AudioTrackType.VOICEOVER,
                    str(tmp_path / "gone.mp3"),
                    8.0,
                    scene_number=1,
                )
            ],
            scenes=1,
        )
    )

    assert any("file not found" in t for t in _texts(view))
    assert not _play_buttons(view)


def test_nothing_generated_shows_a_clear_empty_state_for_all_three(
    qapp: QApplication,
) -> None:
    texts = _texts(_view(_job([])))

    assert any("No voiceover generated yet" in t for t in texts)
    assert any("No sound effects generated yet" in t for t in texts)
    assert any("No background music generated yet" in t for t in texts)


def test_sound_effects_and_music_are_labelled_from_the_plan(
    qapp: QApplication, tmp_path: Path
) -> None:
    sfx = _track(
        AudioTrackType.SOUND_EFFECT,
        _file(tmp_path, "sfx.mp3"),
        2.0,
        start=5.0,
        provider="elevenlabs",
    )
    music = _track(
        AudioTrackType.BACKGROUND_MUSIC,
        _file(tmp_path, "music.mp3"),
        30.0,
        provider="elevenlabs",
    )
    job = _job([sfx, music])
    job.sound_design_plan = SoundDesignPlan(
        sfx_cues=[
            SoundEffectCueDirective(
                scene_number=2,
                generation_prompt="honey drizzling from a spoon",
                rationale="r",
                audio_track_id=str(sfx.id),
                status=SoundDesignItemStatus.GENERATED,
            ),
            SoundEffectCueDirective(
                scene_number=4,
                generation_prompt="a measuring spoon",
                rationale="r",
            ),
        ],
        music_segments=[
            MusicMoodSegment(
                start_scene_number=1,
                end_scene_number=2,
                mood_description="warm gentle piano",
                rationale="r",
                audio_track_id=str(music.id),
                status=SoundDesignItemStatus.GENERATED,
            )
        ],
    )

    texts = _texts(_view(job))

    assert any("1 effect(s) (1 of 2 planned cues generated)" in t for t in texts)
    assert any(
        t.startswith("Scene 2: honey drizzling from a spoon · 2.0s") for t in texts
    )
    assert any("1 track(s) (1 of 1 planned segments generated)" in t for t in texts)
    assert any(t.startswith("Scenes 1-2: warm gentle piano · 30.0s") for t in texts)


def test_tracks_without_a_plan_still_get_a_readable_label(
    qapp: QApplication, tmp_path: Path
) -> None:
    sfx = _track(AudioTrackType.SOUND_EFFECT, _file(tmp_path, "s.mp3"), 1.5, start=12.0)

    assert any(t.startswith("Effect at 12.0s") for t in _texts(_view(_job([sfx]))))
