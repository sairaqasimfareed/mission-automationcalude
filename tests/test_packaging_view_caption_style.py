from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton, QRadioButton  # noqa: E402

from src.desktop.job_store import InMemoryJobStore  # noqa: E402
from src.desktop.views.packaging_view import PackagingView  # noqa: E402
from src.models.enums import JobStatus, WorkflowStage  # noqa: E402
from src.models.video_job import VideoJob  # noqa: E402
from src.services.final_export.final_export_service import (  # noqa: E402
    FinalExportService,
)


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])

    yield app  # type: ignore[misc]


def _job(*, genre_id: str = "genre.documentary") -> VideoJob:
    return VideoJob(
        project_name="Deep Sea Doc",
        channel_name="Ocean Channel",
        niche="documentary",
        topic="Giant squid",
        status=JobStatus.COMPLETED,
        current_stage=WorkflowStage.READY_FOR_UPLOAD,
        genre_id=genre_id,
    )


def _view(*, on_change=lambda: None, tmp_path: Path) -> PackagingView:
    return PackagingView(
        job_store=InMemoryJobStore(),
        seo_package_service=None,  # type: ignore[arg-type]
        thumbnail_package_service=None,  # type: ignore[arg-type]
        final_export_service=FinalExportService(export_root=tmp_path / "exports"),
        on_change=on_change,
    )


def _radio(view: PackagingView, text: str) -> QRadioButton:
    return next(
        radio for radio in view.findChildren(QRadioButton) if radio.text() == text
    )


def _save_button(view: PackagingView) -> QPushButton:
    return next(
        button
        for button in view.findChildren(QPushButton)
        if button.text() == "Save caption style"
    )


def test_shows_one_radio_per_registered_preset_plus_auto(
    qapp: QApplication, tmp_path: Path
) -> None:
    view = _view(tmp_path=tmp_path)
    job = _job()

    view._job_store.add(job)
    view.set_job(job.id)
    view.refresh(job)

    radios = view.findChildren(QRadioButton)

    assert len(radios) == 4
    assert _radio(view, "Auto (genre-selected)") is not None
    assert _radio(view, "Default Subtitle") is not None
    assert _radio(view, "Bold Punchy Subtitle") is not None


def test_marks_the_genre_default_option_in_its_own_label(
    qapp: QApplication, tmp_path: Path
) -> None:
    """genre.documentary's own real default is subtitle.cinematic -
    that option's label must say so, and no other option's label
    should claim it."""

    view = _view(tmp_path=tmp_path)
    job = _job(genre_id="genre.documentary")

    view._job_store.add(job)
    view.set_job(job.id)
    view.refresh(job)

    assert _radio(view, "Cinematic Subtitle (genre default)") is not None
    assert _radio(view, "Default Subtitle").text() == "Default Subtitle"


def test_auto_radio_is_selected_when_the_job_has_no_override(
    qapp: QApplication, tmp_path: Path
) -> None:
    view = _view(tmp_path=tmp_path)
    job = _job()

    view._job_store.add(job)
    view.set_job(job.id)
    view.refresh(job)

    assert _radio(view, "Auto (genre-selected)").isChecked() is True


def test_the_overridden_preset_is_selected_when_the_job_has_one(
    qapp: QApplication, tmp_path: Path
) -> None:
    view = _view(tmp_path=tmp_path)
    job = _job()
    job.subtitle_style_override_preset_id = "subtitle.bold_punchy"

    view._job_store.add(job)
    view.set_job(job.id)
    view.refresh(job)

    assert _radio(view, "Bold Punchy Subtitle").isChecked() is True
    assert _radio(view, "Auto (genre-selected)").isChecked() is False


def test_selecting_a_style_and_saving_persists_the_override_onto_the_job(
    qapp: QApplication, tmp_path: Path
) -> None:
    on_change_calls: list[bool] = []

    view = _view(on_change=lambda: on_change_calls.append(True), tmp_path=tmp_path)
    job = _job()

    view._job_store.add(job)
    view.set_job(job.id)
    view.refresh(job)

    _radio(view, "Default Subtitle").setChecked(True)
    _save_button(view).click()

    stored_job = view._job_store.get(job.id)
    assert stored_job is not None
    assert stored_job.subtitle_style_override_preset_id == "subtitle.default"
    assert on_change_calls == [True]


def test_selecting_auto_and_saving_clears_an_existing_override(
    qapp: QApplication, tmp_path: Path
) -> None:
    view = _view(tmp_path=tmp_path)
    job = _job()
    job.subtitle_style_override_preset_id = "subtitle.bold_punchy"

    view._job_store.add(job)
    view.set_job(job.id)
    view.refresh(job)

    _radio(view, "Auto (genre-selected)").setChecked(True)
    _save_button(view).click()

    stored_job = view._job_store.get(job.id)
    assert stored_job is not None
    assert stored_job.subtitle_style_override_preset_id is None
