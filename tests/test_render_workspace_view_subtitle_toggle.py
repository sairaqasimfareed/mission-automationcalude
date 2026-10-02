from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QCheckBox, QRadioButton  # noqa: E402

from src.desktop.job_store import InMemoryJobStore  # noqa: E402
from src.desktop.views.packaging_view import PackagingView  # noqa: E402
from src.desktop.views.render_workspace_view import RenderWorkspaceView  # noqa: E402
from src.models.enums import JobStatus, WorkflowStage  # noqa: E402
from src.models.video_job import VideoJob  # noqa: E402
from src.services.caption_style_options_service import (  # noqa: E402
    CaptionStyleOptionsService,
)
from src.services.final_export.final_export_service import (  # noqa: E402
    FinalExportService,
)

_LABEL = "Include subtitles in the rendered video"


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


def _view(job: VideoJob, on_change=lambda: None) -> RenderWorkspaceView:
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


def _checkbox(view: RenderWorkspaceView) -> QCheckBox:
    return next(c for c in view.findChildren(QCheckBox) if c.text() == _LABEL)


def test_toggle_defaults_checked(qapp: QApplication) -> None:
    assert _checkbox(_view(_job())).isChecked() is True


def test_toggle_reflects_a_job_with_subtitles_off(qapp: QApplication) -> None:
    job = _job()
    job.subtitles_enabled = False

    assert _checkbox(_view(job)).isChecked() is False


def test_unchecking_saves_onto_the_job_immediately(qapp: QApplication) -> None:
    calls: list[bool] = []
    job = _job()
    view = _view(job, on_change=lambda: calls.append(True))

    _checkbox(view).setChecked(False)

    assert job.subtitles_enabled is False
    assert calls == [True]


def test_rechecking_turns_subtitles_back_on(qapp: QApplication) -> None:
    job = _job()
    job.subtitles_enabled = False
    view = _view(job)

    _checkbox(view).setChecked(True)

    assert job.subtitles_enabled is True


def test_building_the_card_does_not_trigger_a_change(qapp: QApplication) -> None:
    calls: list[bool] = []

    _view(_job(), on_change=lambda: calls.append(True))

    assert calls == []


def test_packaging_no_longer_carries_the_subtitle_checkbox(
    qapp: QApplication, tmp_path: Path
) -> None:
    job = _job()
    job.subtitles_enabled = False
    packaging = PackagingView(
        job_store=InMemoryJobStore(),
        seo_package_service=None,  # type: ignore[arg-type]
        thumbnail_package_service=None,  # type: ignore[arg-type]
        final_export_service=FinalExportService(export_root=tmp_path / "exports"),
        on_change=lambda: None,
    )
    packaging._job_store.add(job)
    packaging.set_job(job.id)
    packaging.refresh(job)

    assert not [c for c in packaging.findChildren(QCheckBox) if "ubtitle" in c.text()]


def _style_radios(view: RenderWorkspaceView) -> list[QRadioButton]:
    return view.findChildren(QRadioButton)


def test_style_options_are_listed_with_an_auto_choice(qapp: QApplication) -> None:
    view = _view(_job())
    texts = [radio.text() for radio in _style_radios(view)]

    assert texts[0] == "Auto (genre-selected)"
    assert len(texts) > 1
    assert [radio for radio in _style_radios(view) if radio.isChecked()] == [
        _style_radios(view)[0]
    ]


def test_style_picker_is_hidden_when_subtitles_are_off(qapp: QApplication) -> None:
    job = _job()
    job.subtitles_enabled = False
    view = _view(job)
    view.show()

    assert all(not radio.isVisible() for radio in _style_radios(view))


def test_style_picker_appears_when_subtitles_are_turned_on(
    qapp: QApplication,
) -> None:
    job = _job()
    job.subtitles_enabled = False
    view = _view(job)
    view.show()

    _checkbox(view).setChecked(True)

    assert all(radio.isVisible() for radio in _style_radios(view))


def test_style_picker_hides_when_subtitles_are_turned_off(
    qapp: QApplication,
) -> None:
    view = _view(_job())
    view.show()

    assert all(radio.isVisible() for radio in _style_radios(view))

    _checkbox(view).setChecked(False)

    assert all(not radio.isVisible() for radio in _style_radios(view))


def test_picking_a_style_saves_it_immediately(qapp: QApplication) -> None:
    calls: list[bool] = []
    job = _job()
    view = _view(job, on_change=lambda: calls.append(True))

    chosen = _style_radios(view)[1]
    chosen.setChecked(True)

    options = CaptionStyleOptionsService().list_options(genre_id=job.genre_id)
    assert job.subtitle_style_override_preset_id == options[0].preset_id
    assert calls == [True]


def test_choosing_auto_clears_the_override(qapp: QApplication) -> None:
    job = _job()
    options = CaptionStyleOptionsService().list_options(genre_id=job.genre_id)
    job.subtitle_style_override_preset_id = options[0].preset_id
    view = _view(job)

    assert _style_radios(view)[1].isChecked()

    _style_radios(view)[0].setChecked(True)

    assert job.subtitle_style_override_preset_id is None


def test_packaging_no_longer_carries_the_caption_style_card(
    qapp: QApplication, tmp_path: Path
) -> None:
    packaging = PackagingView(
        job_store=InMemoryJobStore(),
        seo_package_service=None,  # type: ignore[arg-type]
        thumbnail_package_service=None,  # type: ignore[arg-type]
        final_export_service=FinalExportService(export_root=tmp_path / "exports"),
        on_change=lambda: None,
    )
    job = _job()
    packaging._job_store.add(job)
    packaging.set_job(job.id)
    packaging.refresh(job)

    assert not packaging.findChildren(QRadioButton)
