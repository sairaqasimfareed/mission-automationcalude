from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402
from uuid import UUID  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QCheckBox, QPushButton  # noqa: E402

from src.desktop.views.production_audio_view import ProductionAudioView  # noqa: E402
from src.models.audio_inclusion_preferences import (  # noqa: E402
    AudioInclusionPreferences,
)
from src.models.video_job import VideoJob  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])

    yield app  # type: ignore[misc]


def _job() -> VideoJob:
    return VideoJob(
        project_name="Test",
        channel_name="Channel",
        niche="testing",
        topic="A topic",
        genre_id="genre.horror",
    )


class _FakeJobStore:
    def __init__(self, job: VideoJob) -> None:
        self._job = job

    def get(self, job_id: UUID) -> VideoJob | None:
        return self._job if job_id == self._job.id else None


def _build_view(job: VideoJob) -> ProductionAudioView:
    view = ProductionAudioView(
        job_store=_FakeJobStore(job),  # type: ignore[arg-type]
        media_generation_pipeline=MagicMock(),
        on_change=lambda: None,
    )
    view.set_job(job.id)
    view.refresh(job)

    return view


def _find_checkboxes(view: ProductionAudioView) -> list[QCheckBox]:
    return view.findChildren(QCheckBox)


def _checkbox_by_text(view: ProductionAudioView, text: str) -> QCheckBox:
    return next(box for box in _find_checkboxes(view) if box.text() == text)


def _save_button(view: ProductionAudioView) -> QPushButton:
    return next(
        button
        for button in view.findChildren(QPushButton)
        if button.text() == "Save audio mix settings"
    )


def test_default_preferences_render_with_expected_checked_state(
    qapp: QApplication,
) -> None:
    """
    A fresh job's default AudioInclusionPreferences (native clip off,
    voiceover/music/SFX on) must be reflected exactly in the checkbox
    states on first render - the whole point of the card is that it
    shows the real current state, not just a static form.
    """

    job = _job()
    view = _build_view(job)

    assert (
        _checkbox_by_text(
            view, "Use the AI-generated clips' own native audio"
        ).isChecked()
        is False
    )
    assert _checkbox_by_text(view, "Include voiceover").isChecked() is True
    assert _checkbox_by_text(view, "Include background music").isChecked() is True
    assert _checkbox_by_text(view, "Include sound effects").isChecked() is True


def test_non_default_preferences_render_with_expected_checked_state(
    qapp: QApplication,
) -> None:
    job = _job()
    job.audio_inclusion_preferences = AudioInclusionPreferences(
        include_native_clip_audio=True,
        include_voiceover=False,
        include_music=True,
        include_sound_effects=False,
    )

    view = _build_view(job)

    assert (
        _checkbox_by_text(
            view, "Use the AI-generated clips' own native audio"
        ).isChecked()
        is True
    )
    assert _checkbox_by_text(view, "Include voiceover").isChecked() is False
    assert _checkbox_by_text(view, "Include background music").isChecked() is True
    assert _checkbox_by_text(view, "Include sound effects").isChecked() is False


def test_saving_toggled_checkboxes_updates_job_preferences_in_place(
    qapp: QApplication,
) -> None:
    job = _job()
    view = _build_view(job)

    _checkbox_by_text(view, "Use the AI-generated clips' own native audio").setChecked(
        True
    )
    _checkbox_by_text(view, "Include voiceover").setChecked(False)
    _checkbox_by_text(view, "Include background music").setChecked(False)
    _checkbox_by_text(view, "Include sound effects").setChecked(True)

    _save_button(view).click()

    preferences = job.audio_inclusion_preferences
    assert preferences.include_native_clip_audio is True
    assert preferences.include_voiceover is False
    assert preferences.include_music is False
    assert preferences.include_sound_effects is True


def test_saving_calls_on_change(qapp: QApplication) -> None:
    job = _job()
    on_change = MagicMock()

    view = ProductionAudioView(
        job_store=_FakeJobStore(job),  # type: ignore[arg-type]
        media_generation_pipeline=MagicMock(),
        on_change=on_change,
    )
    view.set_job(job.id)
    view.refresh(job)

    _save_button(view).click()

    on_change.assert_called_once()


def test_saving_leaves_untouched_toggles_at_their_current_value(
    qapp: QApplication,
) -> None:
    """Saving without touching a checkbox must not accidentally flip it -
    each checkbox's saved value comes from its own current UI state,
    which starts pre-filled from the job, not from a fresh default."""

    job = _job()
    job.audio_inclusion_preferences = AudioInclusionPreferences(
        include_native_clip_audio=False,
        include_voiceover=True,
        include_music=True,
        include_sound_effects=True,
    )

    view = _build_view(job)

    # Only flip music off - everything else left alone.
    _checkbox_by_text(view, "Include background music").setChecked(False)

    _save_button(view).click()

    preferences = job.audio_inclusion_preferences
    assert preferences.include_native_clip_audio is False
    assert preferences.include_voiceover is True
    assert preferences.include_music is False
    assert preferences.include_sound_effects is True
