"""
Real, previously-undiagnosed crash fix, 2026-09-24 (see
[[render_pause_test_crash]] memory): a render QThread whose Python
wrapper gets garbage collected while its underlying OS thread is
still actually executing crashes the whole process hard at the Qt/C++
level - RenderOrchestratorService.execute() has no cancellation path
anywhere in its call chain, so the only safe recovery is a genuine
join, never abandonment. Proves RenderWorkspaceView.has_pending_
renders()/wait_for_pending_renders() - the primitive both
MainWindow.closeEvent() and tests/test_desktop_app_integration.py's
own _wait_for_render helper now rely on - against a real, deterministic
slow QThread (not the full render pipeline, which would make this
test's own timing non-deterministic).

A real SECOND bug was found and fixed building this fix, caught by
this test file's own first, failing draft: a bare QThread.wait() can
never actually succeed for this app's plain-QThread-plus-moveToThread
pattern - the worker thread's own event loop only terminates once
thread.quit() actually runs, but that arrives via the exact same
cross-thread QUEUED delivery documented on _RenderWorker (a bound
QObject method, correctly auto-detected as needing queued delivery),
which requires the CALLING thread's own event loop to be pumped.
QThread.wait() blocks that calling thread WITHOUT pumping it, so a
bare wait() call self-deadlocks: it can never see a thread finish
whose own natural termination depends on a signal only wait()'s own
caller could have delivered. wait_for_pending_renders() now
interleaves short, bounded thread.wait() calls with
QApplication.processEvents() internally to break that deadlock.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time  # noqa: E402
from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QObject, QThread, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.desktop.job_store import InMemoryJobStore  # noqa: E402
from src.desktop.views.render_workspace_view import (  # noqa: E402
    RenderWorkspaceView,
)


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])

    yield app  # type: ignore[misc]


class _SlowWorker(QObject):
    """A real worker that blocks for a fixed, deterministic duration -
    stands in for _RenderWorker without depending on the real render
    pipeline's own, load-variable timing."""

    finished = Signal()

    def __init__(self, *, sleep_seconds: float) -> None:
        super().__init__()

        self._sleep_seconds = sleep_seconds

    def run(self) -> None:
        time.sleep(self._sleep_seconds)

        self.finished.emit()


def _view() -> RenderWorkspaceView:
    return RenderWorkspaceView(
        job_store=InMemoryJobStore(),
        render_runtime_factory=object(),  # type: ignore[arg-type]
        asset_workflow_service=object(),  # type: ignore[arg-type]
        on_change=lambda: None,
    )


def _register_slow_render(
    view: RenderWorkspaceView, *, job_id: object, sleep_seconds: float
) -> tuple[QThread, _SlowWorker]:
    thread = QThread()
    worker = _SlowWorker(sleep_seconds=sleep_seconds)
    worker.moveToThread(thread)

    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)

    view._render_threads[job_id] = (thread, worker)  # type: ignore[index]

    thread.start()

    return thread, worker


def test_has_pending_renders_reflects_real_thread_state(
    qapp: QApplication,
) -> None:
    view = _view()

    assert view.has_pending_renders() is False

    _thread, _worker = _register_slow_render(view, job_id="job-1", sleep_seconds=0.3)

    assert view.has_pending_renders() is True

    # A genuine join via the fixed primitive - a bare QThread.wait()
    # here would deadlock (see this file's own module docstring).
    joined = view.wait_for_pending_renders(timeout_ms=5_000)

    assert joined is True
    assert view.has_pending_renders() is False


def test_wait_for_pending_renders_returns_false_on_a_short_timeout(
    qapp: QApplication,
) -> None:
    """
    The real point of this whole fix: a soft timeout must never
    abandon the thread - it returns False (not finished YET), the
    thread keeps running safely, and a longer wait afterward still
    joins it cleanly with no crash.
    """

    view = _view()

    thread, _worker = _register_slow_render(view, job_id="job-2", sleep_seconds=0.5)

    assert view.wait_for_pending_renders(timeout_ms=50) is False

    # The thread must still be genuinely alive and safe to wait on
    # again - not corrupted or torn down by the short timeout above.
    assert view.wait_for_pending_renders(timeout_ms=5_000) is True

    qapp.processEvents()


def test_wait_for_pending_renders_with_no_pending_render_returns_true(
    qapp: QApplication,
) -> None:
    view = _view()

    assert view.wait_for_pending_renders(timeout_ms=50) is True
