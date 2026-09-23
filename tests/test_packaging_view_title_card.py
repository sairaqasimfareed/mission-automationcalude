from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402
from pathlib import Path  # noqa: E402
from uuid import uuid4  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QCheckBox,
    QComboBox,
    QLineEdit,
    QPushButton,
)

from src.desktop.job_store import InMemoryJobStore  # noqa: E402
from src.desktop.views.packaging_view import PackagingView  # noqa: E402
from src.models.enums import JobStatus, Platform, WorkflowStage  # noqa: E402
from src.models.seo import SEOPackage, SEOPlatformMetadata, TitleCandidate  # noqa: E402
from src.models.thumbnail import ThumbnailTextPosition  # noqa: E402
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


def _seo_package(*, selected_title: str) -> SEOPackage:
    return SEOPackage(
        video_job_id=uuid4(),
        title_candidates=[TitleCandidate(text=selected_title)],
        selected_title=selected_title,
        description="A complete, publish-ready description.",
        platform_metadata=SEOPlatformMetadata(platform=Platform.YOUTUBE),
        prompt_version="seo_prompt_v1.0.0",
    )


def _view(*, on_change=lambda: None, tmp_path: Path) -> PackagingView:
    return PackagingView(
        job_store=InMemoryJobStore(),
        seo_package_service=None,  # type: ignore[arg-type]
        thumbnail_package_service=None,  # type: ignore[arg-type]
        final_export_service=FinalExportService(export_root=tmp_path / "exports"),
        on_change=on_change,
    )


def _title_card_checkbox(view: PackagingView) -> QCheckBox:
    return next(
        checkbox
        for checkbox in view.findChildren(QCheckBox)
        if checkbox.text() == "Add an opening title card to this render"
    )


def _save_button(view: PackagingView) -> QPushButton:
    return next(
        button
        for button in view.findChildren(QPushButton)
        if button.text() == "Save title card settings"
    )


def test_title_card_defaults_to_disabled_with_no_override(
    qapp: QApplication, tmp_path: Path
) -> None:
    view = _view(tmp_path=tmp_path)
    job = _job()

    view._job_store.add(job)
    view.set_job(job.id)
    view.refresh(job)

    checkbox = _title_card_checkbox(view)

    assert checkbox.isChecked() is False


def test_title_field_placeholder_shows_auto_resolved_topic_when_no_seo_title(
    qapp: QApplication, tmp_path: Path
) -> None:
    view = _view(tmp_path=tmp_path)
    job = _job()

    view._job_store.add(job)
    view.set_job(job.id)
    view.refresh(job)

    line_edits = [
        widget
        for widget in view.findChildren(QLineEdit)
        if "Auto:" in widget.placeholderText()
    ]

    assert len(line_edits) == 1
    assert line_edits[0].placeholderText() == "Auto: Giant squid"
    assert line_edits[0].text() == ""


def test_title_field_placeholder_prefers_the_real_seo_title_when_one_exists(
    qapp: QApplication, tmp_path: Path
) -> None:
    view = _view(tmp_path=tmp_path)
    job = _job()

    view._job_store.add(job)
    view.set_job(job.id)
    view._job_store.set_seo_package(
        job.id, _seo_package(selected_title="The Real Squid Story")
    )
    view.refresh(job)

    line_edits = [
        widget
        for widget in view.findChildren(QLineEdit)
        if "Auto:" in widget.placeholderText()
    ]

    assert line_edits[0].placeholderText() == "Auto: The Real Squid Story"


def test_existing_manual_override_and_position_are_shown_on_refresh(
    qapp: QApplication, tmp_path: Path
) -> None:
    view = _view(tmp_path=tmp_path)
    job = _job()
    job.title_card_enabled = True
    job.title_card_text = "My Custom Title"
    job.title_card_text_position = ThumbnailTextPosition.CENTER_RIGHT

    view._job_store.add(job)
    view.set_job(job.id)
    view.refresh(job)

    checkbox = _title_card_checkbox(view)
    assert checkbox.isChecked() is True

    line_edits = [
        widget
        for widget in view.findChildren(QLineEdit)
        if widget.text() == "My Custom Title"
    ]
    assert len(line_edits) == 1

    combos = [
        combo
        for combo in view.findChildren(QComboBox)
        if combo.currentText() == "Center right"
    ]
    assert len(combos) == 1


def test_saving_persists_the_toggle_title_and_position_onto_the_job(
    qapp: QApplication, tmp_path: Path
) -> None:
    on_change_calls = []

    view = _view(on_change=lambda: on_change_calls.append(True), tmp_path=tmp_path)
    job = _job()

    view._job_store.add(job)
    view.set_job(job.id)
    view.refresh(job)

    checkbox = _title_card_checkbox(view)
    checkbox.setChecked(True)

    title_input = next(
        widget
        for widget in view.findChildren(QLineEdit)
        if "Auto:" in widget.placeholderText()
    )
    title_input.setText("A Brand New Title")

    position_combo = next(
        combo
        for combo in view.findChildren(QComboBox)
        if combo.currentText() == "Auto (center)"
    )
    position_combo.setCurrentText("Top")

    _save_button(view).click()

    stored_job = view._job_store.get(job.id)
    assert stored_job is not None
    assert stored_job.title_card_enabled is True
    assert stored_job.title_card_text == "A Brand New Title"
    assert stored_job.title_card_text_position == ThumbnailTextPosition.TOP
    assert on_change_calls == [True]


def test_saving_with_an_empty_title_field_clears_the_override_to_none(
    qapp: QApplication, tmp_path: Path
) -> None:
    view = _view(tmp_path=tmp_path)
    job = _job()
    job.title_card_text = "An Old Override"

    view._job_store.add(job)
    view.set_job(job.id)
    view.refresh(job)

    title_input = next(
        widget
        for widget in view.findChildren(QLineEdit)
        if widget.text() == "An Old Override"
    )
    title_input.setText("   ")

    _save_button(view).click()

    stored_job = view._job_store.get(job.id)
    assert stored_job is not None
    assert stored_job.title_card_text is None


def test_saving_with_auto_center_position_stores_none_not_an_explicit_value(
    qapp: QApplication, tmp_path: Path
) -> None:
    view = _view(tmp_path=tmp_path)
    job = _job()
    job.title_card_text_position = ThumbnailTextPosition.BOTTOM

    view._job_store.add(job)
    view.set_job(job.id)
    view.refresh(job)

    position_combo = next(
        combo
        for combo in view.findChildren(QComboBox)
        if combo.currentText() == "Bottom"
    )
    position_combo.setCurrentText("Auto (center)")

    _save_button(view).click()

    stored_job = view._job_store.get(job.id)
    assert stored_job is not None
    assert stored_job.title_card_text_position is None
