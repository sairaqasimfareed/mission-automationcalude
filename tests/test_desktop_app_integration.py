from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.desktop.main_window import MainWindow  # noqa: E402

# QMessageBox.warning() opens a real modal dialog and calls exec(),
# which blocks forever under the offscreen Qt platform (no display to
# dismiss it). Every test in this module patches it out so a genuine
# application error can never hang the test suite - discovered the
# hard way while building this integration test.


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])

    yield app  # type: ignore[misc]


@pytest.fixture
def no_blocking_dialogs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.desktop.views.project_form_view.QMessageBox.warning",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "src.desktop.views.project_detail_view.QMessageBox.warning",
        lambda *args, **kwargs: None,
    )


def test_main_window_constructs_and_navigates(
    qapp: QApplication,
    no_blocking_dialogs: None,
) -> None:
    window = MainWindow()

    window.show_new_project()
    assert window._stack.currentWidget() is window._form_view

    window.show_settings()
    assert window._stack.currentWidget() is window._settings_view

    window.show_dashboard()
    assert window._stack.currentWidget() is window._dashboard_view


def test_create_project_runs_workflow_steps_and_generates_seo(
    qapp: QApplication,
    no_blocking_dialogs: None,
) -> None:
    window = MainWindow()

    window.show_new_project()
    form = window._form_view

    form._project_name.setText("Deep Sea Documentary")
    form._channel_name.setText("Ocean Channel")
    form._topic.setText("Deep sea creatures")
    form._video_type.setText("long-form documentary")
    form._niche.setText("ocean-life")
    form._duration_seconds.setValue(600)

    form._handle_create_clicked()

    jobs = window._job_store.list_all()

    assert len(jobs) == 1

    job = jobs[0]

    assert job.research is None
    assert job.script is None

    window._open_project(job.id)

    assert window._detail_view._job_id == job.id

    window._detail_view._handle_run_research()
    assert job.research is not None

    window._detail_view._handle_run_script()
    assert job.script is not None

    window._detail_view._handle_run_originality()
    assert job.originality_review is not None

    window._detail_view._handle_plan_scenes()
    assert job.scenes

    window._detail_view._handle_generate_seo("Ocean enthusiasts")

    seo_package = window._job_store.get_seo_package(job.id)

    assert seo_package is not None
    assert seo_package.selected_title is not None

    window.show_dashboard()

    assert window._dashboard_view._table.rowCount() == 1


def test_thumbnail_generation_failure_does_not_crash(
    qapp: QApplication,
    no_blocking_dialogs: None,
) -> None:
    """
    Thumbnail generation is expected to fail cleanly in dry-run mode
    (documented Sprint 23 limitation: the generic dry-run LLM stub
    cannot produce the structured CONCEPT/HOOK/PROMPT format thumbnail
    parsing requires). This confirms the failure is caught and shown
    through the (patched-out) dialog rather than propagating or
    hanging.
    """

    window = MainWindow()

    window.show_new_project()
    form = window._form_view

    form._project_name.setText("Deep Sea Documentary")
    form._channel_name.setText("Ocean Channel")
    form._topic.setText("Deep sea creatures")
    form._video_type.setText("long-form documentary")
    form._niche.setText("ocean-life")
    form._duration_seconds.setValue(600)

    form._handle_create_clicked()

    job = window._job_store.list_all()[0]
    window._open_project(job.id)

    window._detail_view._handle_run_research()
    window._detail_view._handle_run_script()

    window._detail_view._handle_generate_thumbnail("Ocean enthusiasts")

    assert window._job_store.get_thumbnail(job.id) is None
