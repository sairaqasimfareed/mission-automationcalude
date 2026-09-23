from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QCheckBox, QPushButton  # noqa: E402

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


def _job() -> VideoJob:
    return VideoJob(
        project_name="Deep Sea Doc",
        channel_name="Ocean Channel",
        niche="documentary",
        topic="Giant squid",
        status=JobStatus.COMPLETED,
        current_stage=WorkflowStage.READY_FOR_UPLOAD,
    )


def _view(*, on_change=lambda: None, tmp_path: Path) -> PackagingView:
    return PackagingView(
        job_store=InMemoryJobStore(),
        seo_package_service=None,  # type: ignore[arg-type]
        thumbnail_package_service=None,  # type: ignore[arg-type]
        final_export_service=FinalExportService(export_root=tmp_path / "exports"),
        on_change=on_change,
    )


def _subtitles_checkbox(view: PackagingView) -> QCheckBox:
    return next(
        checkbox
        for checkbox in view.findChildren(QCheckBox)
        if checkbox.text() == "Include subtitles in the final video"
    )


def _save_button(view: PackagingView) -> QPushButton:
    return next(
        button
        for button in view.findChildren(QPushButton)
        if button.text() == "Save subtitle setting"
    )


def test_subtitle_checkbox_defaults_checked(qapp: QApplication, tmp_path: Path) -> None:
    view = _view(tmp_path=tmp_path)
    job = _job()

    view._job_store.add(job)
    view.set_job(job.id)
    view.refresh(job)

    assert _subtitles_checkbox(view).isChecked() is True


def test_subtitle_checkbox_reflects_an_existing_disabled_job(
    qapp: QApplication, tmp_path: Path
) -> None:
    view = _view(tmp_path=tmp_path)
    job = _job()
    job.subtitles_enabled = False

    view._job_store.add(job)
    view.set_job(job.id)
    view.refresh(job)

    assert _subtitles_checkbox(view).isChecked() is False


def test_unchecking_and_saving_persists_the_toggle_onto_the_job(
    qapp: QApplication, tmp_path: Path
) -> None:
    on_change_calls: list[bool] = []

    view = _view(on_change=lambda: on_change_calls.append(True), tmp_path=tmp_path)
    job = _job()

    view._job_store.add(job)
    view.set_job(job.id)
    view.refresh(job)

    checkbox = _subtitles_checkbox(view)
    checkbox.setChecked(False)

    _save_button(view).click()

    stored_job = view._job_store.get(job.id)
    assert stored_job is not None
    assert stored_job.subtitles_enabled is False
    assert on_change_calls == [True]


def test_checking_and_saving_re_enables_subtitles_on_the_job(
    qapp: QApplication, tmp_path: Path
) -> None:
    view = _view(tmp_path=tmp_path)
    job = _job()
    job.subtitles_enabled = False

    view._job_store.add(job)
    view.set_job(job.id)
    view.refresh(job)

    checkbox = _subtitles_checkbox(view)
    checkbox.setChecked(True)

    _save_button(view).click()

    stored_job = view._job_store.get(job.id)
    assert stored_job is not None
    assert stored_job.subtitles_enabled is True
