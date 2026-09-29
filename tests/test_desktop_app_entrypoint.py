from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import signal  # noqa: E402
from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.desktop.app import _install_ctrl_c_handler  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])

    yield app  # type: ignore[misc]


class _FakeWindow:
    """Duck-typed stand-in for MainWindow - only close() matters for
    this test, and a real MainWindow's own closeEvent() (pending-
    render wait, browser-worker shutdown) has its own dedicated tests
    elsewhere."""

    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


@pytest.fixture
def restore_sigint_handler() -> Iterator[None]:
    """
    _install_ctrl_c_handler mutates real, process-wide signal state -
    every test using it must restore the original handler afterward,
    or it leaks into every other test (and pytest's own Ctrl+C
    handling) that runs later in the same process.
    """

    original_handler = signal.getsignal(signal.SIGINT)

    yield

    signal.signal(signal.SIGINT, original_handler)


def test_ctrl_c_closes_the_window(
    qapp: QApplication, restore_sigint_handler: None
) -> None:
    """
    Real-world finding, 2026-09-30: stopping the app with Ctrl+C in
    its own launching terminal never ran MainWindow.closeEvent() at
    all - Qt's C++ event loop blocks Python bytecode execution, so a
    signal handler installed the ordinary way never actually fires.
    Confirmed real symptom: a recurring, unrelated-looking Node.js
    "EPIPE: broken pipe" crash trace from the orphaned Playwright
    driver process, since _shutdown_browser_workers() (wired into
    closeEvent()) never got a chance to run.
    """

    window = _FakeWindow()

    _install_ctrl_c_handler(qapp, window)  # type: ignore[arg-type]

    handler = signal.getsignal(signal.SIGINT)
    assert callable(handler)
    handler(signal.SIGINT, None)  # type: ignore[operator]

    assert window.close_calls == 1


def test_installing_the_handler_twice_still_closes_on_the_latest_window(
    qapp: QApplication, restore_sigint_handler: None
) -> None:
    """A second call (e.g. a future re-init) must not leave the OLD
    window's close() wired to Ctrl+C instead of the current one."""

    first_window = _FakeWindow()
    second_window = _FakeWindow()

    _install_ctrl_c_handler(qapp, first_window)  # type: ignore[arg-type]
    _install_ctrl_c_handler(qapp, second_window)  # type: ignore[arg-type]

    handler = signal.getsignal(signal.SIGINT)
    assert callable(handler)
    handler(signal.SIGINT, None)  # type: ignore[operator]

    assert first_window.close_calls == 0
    assert second_window.close_calls == 1
