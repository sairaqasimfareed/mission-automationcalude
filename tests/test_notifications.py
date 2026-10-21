"""Messages in the corner and the working bar (src/desktop/notifications.py)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget  # noqa: E402

from src.desktop import notifications  # noqa: E402
from src.desktop.notifications import NotificationCenter  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])

    yield app  # type: ignore[misc]


@pytest.fixture()
def center(qapp: QApplication) -> Iterator[NotificationCenter]:
    window = QMainWindow()
    window.setCentralWidget(QWidget())
    window.resize(900, 600)
    window.show()
    installed = NotificationCenter(window)
    notifications.install(installed)

    yield installed

    notifications.install(None)
    window.close()


def test_without_a_window_every_call_does_nothing(qapp: QApplication) -> None:
    notifications.install(None)

    notifications.notify_success("saved")
    token = notifications.begin_busy("working")
    notifications.end_busy(token)

    assert token == 0


def test_a_success_message_appears(center: NotificationCenter) -> None:
    notifications.notify_success("Project settings saved")

    assert center.toast_texts == ["Project settings saved"]


def test_messages_are_limited_so_they_never_pile_up(center: NotificationCenter) -> None:
    for number in range(10):
        notifications.notify_success(f"message {number}")

    assert len(center.toast_texts) == 4
    assert center.toast_texts[-1] == "message 9"


def test_the_working_bar_shows_what_runs_until_it_ends(
    center: NotificationCenter,
) -> None:
    first = notifications.begin_busy("Working: generating the voiceover...")
    second = notifications.begin_busy("Working: generating the music...")

    assert center.busy_texts == [
        "Working: generating the voiceover...",
        "Working: generating the music...",
    ]
    assert center._busy_label.text().startswith(
        "Working: generating the music..."
    )  # noqa: SLF001
    assert "(+1 more)" in center._busy_label.text()  # noqa: SLF001

    notifications.end_busy(first)
    notifications.end_busy(second)

    assert center.busy_texts == []
    assert center._holder.isHidden() is True  # noqa: SLF001


def test_a_finished_stage_in_the_content_tab_says_so(
    center: NotificationCenter,
) -> None:
    from src.desktop.job_store import InMemoryJobStore
    from tests.test_content_studio_video_provider_gui import _job, _view

    store = InMemoryJobStore()
    job = _job()
    store.add(job)
    view = _view(store)
    view.set_job(job.id)

    view._run_stage(  # noqa: SLF001
        job,
        lambda target: None,
        label="visual continuity bible",
        failure="Could not make it",
    )

    assert "Visual continuity bible - done" in center.toast_texts
