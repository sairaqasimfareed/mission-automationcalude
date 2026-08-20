from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget  # noqa: E402

from src.desktop.recovery_dialog import show_recoverable_error  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])

    yield app  # type: ignore[misc]


def test_no_retry_falls_back_to_plain_warning_dialog(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        staticmethod(
            lambda parent, title, message: calls.append((parent, title, message))
        ),
    )

    parent = QWidget()
    show_recoverable_error(parent, "Step failed", "Something broke")

    assert calls == [(parent, "Step failed", "Something broke")]


def test_clicking_retry_invokes_the_retry_callback(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retried = []

    def _fake_exec(self: QMessageBox) -> int:
        # Simulate the user clicking the Retry action button rather
        # than actually blocking on a real modal event loop.
        for candidate in self.buttons():
            if self.buttonRole(candidate) == QMessageBox.ButtonRole.ActionRole:
                self.setProperty("_clicked", candidate)

                return 0

        return 0

    monkeypatch.setattr(QMessageBox, "exec", _fake_exec)
    monkeypatch.setattr(
        QMessageBox,
        "clickedButton",
        lambda self: self.property("_clicked"),
    )

    parent = QWidget()
    show_recoverable_error(
        parent,
        "Step failed",
        "Something broke",
        on_retry=lambda: retried.append(True),
    )

    assert retried == [True]


def test_dismissing_without_retry_does_not_invoke_the_callback(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retried = []

    def _fake_exec(self: QMessageBox) -> int:
        for candidate in self.buttons():
            if self.buttonRole(candidate) == QMessageBox.ButtonRole.AcceptRole:
                self.setProperty("_clicked", candidate)

                return 0

        return 0

    monkeypatch.setattr(QMessageBox, "exec", _fake_exec)
    monkeypatch.setattr(
        QMessageBox,
        "clickedButton",
        lambda self: self.property("_clicked"),
    )

    parent = QWidget()
    show_recoverable_error(
        parent,
        "Step failed",
        "Something broke",
        on_retry=lambda: retried.append(True),
    )

    assert retried == []
