"""
Stages and automation run in the background (2026-10-06).

Live: a manual-script project's Resume automation made four paid Claude calls on
the window's own thread (one took 80s), the window froze, was force-closed, and
every result was lost; then each stage button froze it again (the visual
continuity bible took 117s). Stages now run on a worker thread with their own copy
of the job, and every finished stage is saved as it completes.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading  # noqa: E402
from unittest.mock import patch  # noqa: E402

from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

from src.desktop.job_store import InMemoryJobStore  # noqa: E402
from src.models.video_job import VideoJob  # noqa: E402
from tests.test_content_studio_content_intelligence_gui import (  # noqa: E402
    _job,
    _view,
)
from tests.test_content_studio_content_intelligence_gui import (  # noqa: E402
    qapp as qapp,  # noqa: PLC0414 - fixture
)


class _RecordingStore(InMemoryJobStore):
    def __init__(self) -> None:
        super().__init__()
        self.adds: list[VideoJob] = []

    def add(self, job: VideoJob) -> None:
        self.adds.append(job)
        super().add(job)


def _background_view(store: _RecordingStore):  # type: ignore[no-untyped-def]
    job = _job()
    store.add(job)
    store.adds.clear()
    view = _view(store)
    view._run_stages_in_background = True  # noqa: SLF001
    changes: list[int] = []
    view._on_change = lambda: changes.append(1)  # type: ignore[assignment]  # noqa: SLF001
    view.set_job(job.id)
    view.refresh(job)

    return view, job, changes


def _threads(view):  # type: ignore[no-untyped-def]
    return [
        *view._stage_threads.values(),  # noqa: SLF001
        *view._automation_threads.values(),  # noqa: SLF001
    ]


def _join(app: QApplication, view) -> None:  # type: ignore[no-untyped-def]
    for thread, _worker in _threads(view):
        thread.wait(5000)

    for _ in range(30):
        app.processEvents()


def _texts(view) -> list[str]:  # type: ignore[no-untyped-def]
    # The tests stub on_change, so do the refresh the real window would.
    job = view._current_job()  # noqa: SLF001

    if job is not None:
        view.refresh(job)

    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    return [label.text() for label in view.findChildren(QLabel)]


# ---- one stage ---------------------------------------------------------


def test_a_stage_runs_on_a_worker_thread_not_the_window_thread(
    qapp: QApplication,  # noqa: F811
) -> None:
    view, job, changes = _background_view(_RecordingStore())
    ran_on: list[int] = []

    view._run_stage(  # noqa: SLF001
        job,
        lambda j: ran_on.append(threading.get_ident()),
        label="shot plan",
        failure="Could not do it",
    )
    _join(qapp, view)

    assert ran_on and ran_on[0] != threading.get_ident()


def test_the_window_shows_what_is_running_while_it_runs(
    qapp: QApplication,  # noqa: F811
) -> None:
    view, job, _ = _background_view(_RecordingStore())
    release = threading.Event()

    view._run_stage(  # noqa: SLF001
        job, lambda j: release.wait(5), label="visual continuity bible", failure="x"
    )

    try:
        view.refresh(job)

        assert any("Working: visual continuity bible" in t for t in _texts(view))
        assert view.has_pending_automation()
    finally:
        release.set()
        _join(qapp, view)

    assert not view.has_pending_automation()
    assert not any("Working:" in t for t in _texts(view))


def test_a_finished_stage_is_saved_and_the_view_refreshed(
    qapp: QApplication,  # noqa: F811
) -> None:
    store = _RecordingStore()
    view, job, changes = _background_view(store)

    def stage(j: VideoJob) -> None:
        j.warnings.append("done by the worker")

    view._run_stage(job, stage, label="x", failure="x")  # noqa: SLF001
    changes_before = len(changes)
    _join(qapp, view)

    assert store.adds, "the result must be saved"
    assert "done by the worker" in store.adds[-1].warnings
    assert len(changes) > changes_before  # refreshed on completion


def test_the_stage_works_on_a_copy_not_the_live_job(
    qapp: QApplication,  # noqa: F811
) -> None:
    view, job, _ = _background_view(_RecordingStore())
    seen: list[int] = []

    view._run_stage(  # noqa: SLF001
        job, lambda j: seen.append(id(j)), label="x", failure="x"
    )
    _join(qapp, view)

    assert seen and seen[0] != id(job)


def test_a_second_click_while_it_runs_is_ignored(
    qapp: QApplication,  # noqa: F811
) -> None:
    """Each Claude call is paid for - one stage at a time per project."""

    view, job, _ = _background_view(_RecordingStore())
    release = threading.Event()
    calls: list[int] = []

    def slow(j: VideoJob) -> None:
        calls.append(1)
        release.wait(5)

    view._run_stage(job, slow, label="x", failure="x")  # noqa: SLF001

    try:
        view._run_stage(job, slow, label="x", failure="x")  # noqa: SLF001
        view._run_stage(job, slow, label="x", failure="x")  # noqa: SLF001
    finally:
        release.set()
        _join(qapp, view)

    assert calls == [1]


def test_a_failing_stage_reports_the_error_and_keeps_what_it_changed(
    qapp: QApplication,  # noqa: F811
) -> None:
    store = _RecordingStore()
    view, job, _ = _background_view(store)

    def stage(j: VideoJob) -> None:
        j.warnings.append("partial progress")

        raise RuntimeError("Claude said no")

    with patch("src.desktop.views.content_studio_view.show_recoverable_error") as shown:
        view._run_stage(  # noqa: SLF001
            job, stage, label="x", failure="Could not generate the thing"
        )
        _join(qapp, view)

    assert shown.called
    assert "Could not generate the thing: Claude said no" in shown.call_args[0][2]
    saved = store.adds[-1]
    assert "partial progress" in saved.warnings
    assert any("Claude said no" in e for e in saved.errors)


def test_an_unexpected_kind_of_error_is_reported_not_lost(
    qapp: QApplication,  # noqa: F811
) -> None:
    store = _RecordingStore()
    view, job, _ = _background_view(store)

    def stage(j: VideoJob) -> None:
        raise KeyError("missing")

    with patch("src.desktop.views.content_studio_view.show_recoverable_error") as shown:
        view._run_stage(job, stage, label="x", failure="Stage failed")  # noqa: SLF001
        _join(qapp, view)

    assert shown.called
    assert "KeyError" in shown.call_args[0][2]
    assert not view._stage_labels  # noqa: SLF001  # not left looking busy


def test_after_a_failure_the_stage_can_be_run_again(
    qapp: QApplication,  # noqa: F811
) -> None:
    view, job, _ = _background_view(_RecordingStore())
    runs: list[int] = []

    def flaky(j: VideoJob) -> None:
        runs.append(1)

        if len(runs) == 1:
            raise RuntimeError("first time fails")

    with patch("src.desktop.views.content_studio_view.show_recoverable_error"):
        view._run_stage(job, flaky, label="x", failure="x")  # noqa: SLF001
        _join(qapp, view)
        view._run_stage(job, flaky, label="x", failure="x")  # noqa: SLF001
        _join(qapp, view)

    assert runs == [1, 1]


def test_without_background_mode_a_stage_still_runs_inline_as_before(
    qapp: QApplication,  # noqa: F811
) -> None:
    store = _RecordingStore()
    job = _job()
    store.add(job)
    view = _view(store)  # default: run_stages_in_background=False
    view.set_job(job.id)
    view.refresh(job)
    ran_on: list[int] = []

    view._run_stage(  # noqa: SLF001
        job, lambda j: ran_on.append(threading.get_ident()), label="x", failure="x"
    )

    assert ran_on == [threading.get_ident()]  # synchronous, same thread
    assert not view._stage_threads  # noqa: SLF001


def test_the_real_app_turns_background_mode_on(
    qapp: QApplication,
) -> None:  # noqa: F811
    from pathlib import Path

    source = Path("src/desktop/views/project_workspace_view.py").read_text(
        encoding="utf-8"
    )

    assert "run_stages_in_background=True" in source


# ---- Resume automation -------------------------------------------------


def test_automation_saves_every_stage_as_it_finishes(
    qapp: QApplication,  # noqa: F811
) -> None:
    """The point of the whole change: a stage that finished and was paid for is on
    disk before the next one starts."""

    store = _RecordingStore()
    view, job, _ = _background_view(store)
    gate = threading.Event()
    adds_when_second_stage_starts: list[int] = []

    def fake_run_all(j: VideoJob, *, on_stage_complete) -> VideoJob:  # type: ignore[no-untyped-def]
        j.warnings.append("stage one done")
        on_stage_complete(j, "continuity_bible")
        gate.wait(5)  # the GUI thread gets to handle the first stage
        adds_when_second_stage_starts.append(len(store.adds))
        j.warnings.append("stage two done")
        on_stage_complete(j, "scene_planning")

        return j

    view._content_intelligence_pipeline.run_all = fake_run_all  # type: ignore[method-assign]  # noqa: SLF001
    view._handle_run_automation()  # noqa: SLF001

    try:
        for _ in range(100):  # let the first stage's snapshot reach the store
            qapp.processEvents()

            if store.adds:
                break
    finally:
        gate.set()
        _join(qapp, view)

    assert adds_when_second_stage_starts == [1]  # stage one was saved BEFORE stage two
    assert "stage two done" in store.adds[-1].warnings
    assert any("stage one done" in a.warnings for a in store.adds)


def test_the_automation_button_shows_it_is_running_and_cannot_be_pressed_again(
    qapp: QApplication,  # noqa: F811
) -> None:
    store = _RecordingStore()
    view, job, _ = _background_view(store)
    gate = threading.Event()

    def fake_run_all(j: VideoJob, *, on_stage_complete) -> VideoJob:  # type: ignore[no-untyped-def]
        gate.wait(5)

        return j

    view._content_intelligence_pipeline.run_all = fake_run_all  # type: ignore[method-assign]  # noqa: SLF001
    view._handle_run_automation()  # noqa: SLF001

    try:
        view.refresh(job)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        button = next(
            b
            for b in view.findChildren(QPushButton)
            if b.text() == "Automation running..."
        )

        assert not button.isEnabled()

        view._handle_run_automation()  # noqa: SLF001  # a second press does nothing

        assert len(view._automation_threads) == 1  # noqa: SLF001
    finally:
        gate.set()
        _join(qapp, view)


def test_an_automation_failure_keeps_the_stages_that_finished(
    qapp: QApplication,  # noqa: F811
) -> None:
    store = _RecordingStore()
    view, job, _ = _background_view(store)

    def fake_run_all(j: VideoJob, *, on_stage_complete) -> VideoJob:  # type: ignore[no-untyped-def]
        j.warnings.append("bible done")
        on_stage_complete(j, "continuity_bible")

        raise RuntimeError("scene planner failed")

    view._content_intelligence_pipeline.run_all = fake_run_all  # type: ignore[method-assign]  # noqa: SLF001

    with patch("src.desktop.views.content_studio_view.show_recoverable_error") as shown:
        view._handle_run_automation()  # noqa: SLF001
        _join(qapp, view)

    assert shown.called
    assert "Every stage that finished before this was saved" in shown.call_args[0][2]
    final = store.adds[-1]
    assert "bible done" in final.warnings
    assert any("scene planner failed" in e for e in final.errors)
    assert not view._automation_job_ids  # noqa: SLF001


def test_closing_waits_for_a_running_stage_instead_of_tearing_it_down(
    qapp: QApplication,  # noqa: F811
) -> None:
    view, job, _ = _background_view(_RecordingStore())
    release = threading.Event()
    timer = threading.Timer(0.3, release.set)

    view._run_stage(
        job, lambda j: release.wait(5), label="x", failure="x"
    )  # noqa: SLF001
    timer.start()

    try:
        joined = view.wait_for_pending_automation(timeout_ms=4000)
    finally:
        release.set()
        timer.cancel()
        _join(qapp, view)

    assert joined is True
    assert not view.has_pending_automation()
