"""
Every workspace tab rebuilds all its cards on every refresh and used to throw the
operator back to the top after any action (reported live, 2026-10-07). The shared
ScrollKeeper puts the position back; these tests scroll down, refresh, let the
layout settle, and check the position is still there.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402
from uuid import UUID, uuid4  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QEvent, QThread  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QFrame,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.desktop.scroll_preservation import keep_scroll_on_refresh  # noqa: E402
from src.desktop.views.production_audio_view import ProductionAudioView  # noqa: E402
from src.models.audio_timeline import AudioTimeline  # noqa: E402
from src.models.audio_track import (  # noqa: E402
    AudioTrack,
    AudioTrackStatus,
    AudioTrackType,
)
from src.models.scene import Scene  # noqa: E402
from src.models.video_job import VideoJob  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])

    yield app  # type: ignore[misc]


def _settle(app: QApplication, view: QWidget | None = None) -> None:
    """Let the layout pass run, then wait for the keeper to finish settling."""

    waited = 0

    while waited < 8000:
        app.processEvents()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QThread.msleep(10)
        waited += 10
        keeper = getattr(view, "scroll_keeper", None)

        if waited >= 100 and (keeper is None or not keeper.is_settling):
            break


class _Job:
    def __init__(self) -> None:
        self.id: UUID = uuid4()


class _TabView(QWidget):
    """A stand-in tab built the way the real ones are: a scroll area whose cards
    are torn down and rebuilt on every refresh."""

    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        container = QWidget()
        self._layout = QVBoxLayout(container)
        scroll_area.setWidget(container)
        outer.addWidget(scroll_area)
        self.scroll_area = scroll_area
        keep_scroll_on_refresh(self, scroll_area)

    def refresh(self, job: object) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)

            if item is not None and item.widget() is not None:
                item.widget().deleteLater()

        for index in range(60):
            frame = QFrame()
            inner = QVBoxLayout(frame)
            inner.addWidget(QLabel(f"Card {index}"))
            frame.setMinimumHeight(60)
            self._layout.addWidget(frame)


def _shown(view: QWidget, app: QApplication) -> None:
    view.resize(600, 400)
    view.show()
    _settle(app, view)


def test_a_refresh_keeps_the_scroll_position(qapp: QApplication) -> None:
    view = _TabView()
    job = _Job()
    view.refresh(job)
    _shown(view, qapp)
    bar = view.scroll_area.verticalScrollBar()
    assert bar.maximum() > 500

    bar.setValue(900)
    view.refresh(job)
    _settle(qapp, view)

    assert bar.value() == 900


def test_several_refreshes_in_a_row_keep_the_position(qapp: QApplication) -> None:
    """One action can refresh the tab several times in quick succession; the
    position taken mid-rebuild (a collapsed range reads as 0) must not win."""

    view = _TabView()
    job = _Job()
    view.refresh(job)
    _shown(view, qapp)
    bar = view.scroll_area.verticalScrollBar()
    bar.setValue(1200)

    for _ in range(5):
        view.refresh(job)

    _settle(qapp, view)

    assert bar.value() == 1200


def test_a_different_project_starts_at_the_top(qapp: QApplication) -> None:
    view = _TabView()
    view.refresh(_Job())
    _shown(view, qapp)
    bar = view.scroll_area.verticalScrollBar()
    bar.setValue(900)

    view.refresh(_Job())
    _settle(qapp, view)

    assert bar.value() == 0


def test_the_operators_own_scrolling_between_refreshes_is_kept(
    qapp: QApplication,
) -> None:
    view = _TabView()
    job = _Job()
    view.refresh(job)
    _shown(view, qapp)
    bar = view.scroll_area.verticalScrollBar()
    bar.setValue(900)
    view.refresh(job)
    _settle(qapp, view)

    bar.setValue(300)
    _settle(qapp, view)
    view.refresh(job)
    _settle(qapp, view)

    assert bar.value() == 300


def test_the_real_audio_tab_keeps_its_position(qapp: QApplication) -> None:
    job = VideoJob(
        project_name="Test", channel_name="Channel", niche="testing", topic="A topic"
    )
    job.scenes = [
        Scene(
            scene_number=n,
            title=f"Scene {n}",
            narration=f"Narration {n}.",
            visual_prompt=f"Visual {n}.",
            estimated_duration_seconds=8,
        )
        for n in range(1, 4)
    ]
    job.audio_timeline = AudioTimeline(
        tracks=[
            AudioTrack(
                track_type=AudioTrackType.SOUND_EFFECT,
                source_file=f"cue_{n}.wav",
                duration_seconds=2.0,
                start_time_seconds=float(n),
                status=AudioTrackStatus.READY,
                provider="elevenlabs",
                metadata={"scene_number": 1 + n % 3},
            )
            for n in range(40)
        ]
    )
    store = MagicMock()
    store.get.return_value = job
    view = ProductionAudioView(
        job_store=store,
        media_generation_pipeline=MagicMock(),
        on_change=lambda: None,
    )
    view.set_job(job.id)
    view.refresh(job)
    _shown(view, qapp)
    bar = view.findChild(QScrollArea).verticalScrollBar()  # type: ignore[union-attr]
    assert bar.maximum() > 300

    bar.setValue(bar.maximum() // 2)
    wanted = bar.value()
    view.refresh(job)
    _settle(qapp, view)

    assert bar.value() == wanted


def test_a_restore_still_waiting_when_the_tab_is_closed_does_not_raise(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Seen in the full suite: the settle timer fired after the view (and its scroll
    bar) had been deleted and raised "Internal C++ object already deleted"."""

    import sys

    import shiboken6

    import src.desktop.scroll_preservation as module

    monkeypatch.setattr(module, "_MAX_SETTLE_MILLISECONDS", 60)
    monkeypatch.setattr(module, "_QUIET_MILLISECONDS", 30)
    errors: list[object] = []
    monkeypatch.setattr(sys, "excepthook", lambda *args: errors.append(args))

    view = _TabView()
    job = _Job()
    view.refresh(job)
    view.refresh(job)  # starts a restore that is still waiting
    shiboken6.delete(view.scroll_area)

    for _ in range(30):
        qapp.processEvents()
        QThread.msleep(10)

    assert errors == []
