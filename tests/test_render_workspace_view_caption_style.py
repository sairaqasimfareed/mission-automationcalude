from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QRadioButton  # noqa: E402

from src.desktop.job_store import InMemoryJobStore  # noqa: E402
from src.desktop.views.render_workspace_view import RenderWorkspaceView  # noqa: E402
from src.models.enums import JobStatus, WorkflowStage  # noqa: E402
from src.models.video_job import VideoJob  # noqa: E402


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


def _view(job: VideoJob, *, on_change=lambda: None) -> RenderWorkspaceView:
    store = InMemoryJobStore()
    store.add(job)

    view = RenderWorkspaceView(
        job_store=store,
        render_runtime_factory=object(),  # type: ignore[arg-type]
        asset_workflow_service=object(),  # type: ignore[arg-type]
        on_change=on_change,
    )
    view.set_job(job.id)
    view.refresh(job)

    return view


def _radio(view: RenderWorkspaceView, text: str) -> QRadioButton:
    return next(
        radio for radio in view.findChildren(QRadioButton) if radio.text() == text
    )


def test_shows_one_radio_per_registered_preset_plus_auto(qapp: QApplication) -> None:
    view = _view(_job())

    assert len(view.findChildren(QRadioButton)) == 4
    assert _radio(view, "Auto (genre-selected)") is not None
    assert _radio(view, "Default Subtitle") is not None
    assert _radio(view, "Bold Punchy Subtitle") is not None


def test_marks_the_genre_default_option_in_its_own_label(qapp: QApplication) -> None:
    """genre.documentary's own real default is subtitle.cinematic -
    that option's label must say so, and no other option's label
    should claim it."""

    view = _view(_job(genre_id="genre.documentary"))

    assert _radio(view, "Cinematic Subtitle (genre default)") is not None
    assert _radio(view, "Default Subtitle").text() == "Default Subtitle"


def test_auto_radio_is_selected_when_the_job_has_no_override(
    qapp: QApplication,
) -> None:
    view = _view(_job())

    assert _radio(view, "Auto (genre-selected)").isChecked() is True


def test_the_overridden_preset_is_selected_when_the_job_has_one(
    qapp: QApplication,
) -> None:
    job = _job()
    job.subtitle_style_override_preset_id = "subtitle.bold_punchy"
    view = _view(job)

    assert _radio(view, "Bold Punchy Subtitle").isChecked() is True
    assert _radio(view, "Auto (genre-selected)").isChecked() is False


def test_selecting_a_style_persists_the_override_immediately(
    qapp: QApplication,
) -> None:
    on_change_calls: list[bool] = []
    job = _job()
    view = _view(job, on_change=lambda: on_change_calls.append(True))

    _radio(view, "Default Subtitle").setChecked(True)

    assert job.subtitle_style_override_preset_id == "subtitle.default"
    assert on_change_calls == [True]


def test_selecting_auto_clears_an_existing_override(qapp: QApplication) -> None:
    job = _job()
    job.subtitle_style_override_preset_id = "subtitle.bold_punchy"
    view = _view(job)

    _radio(view, "Auto (genre-selected)").setChecked(True)

    assert job.subtitle_style_override_preset_id is None
