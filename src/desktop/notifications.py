"""Messages and a working indicator for the whole window.

Two things every action in the app was missing:

* a short message in the corner when something worked ("Project settings saved") - it fades by itself, so it
  never needs a click; an error keeps its own dialog;
* a bar at the bottom of the window that says what is running ("Working: visual continuity bible...") for as
  long as it runs, whichever tab is open.

The window creates one NotificationCenter and installs it; views call the module functions below. Without an
installed center (tests, a view built on its own) every function does nothing, so no view depends on it.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QWidget,
)

_TOAST_SECONDS = 3.5
_MAXIMUM_TOASTS = 4
_MARGIN = 16

_ACCENT = {"success": "#2f9e5a", "info": "#4a6fd1", "warning": "#d08a1e"}


class _Toast(QLabel):
    def __init__(self, parent: QWidget, text: str, kind: str) -> None:
        super().__init__(text, parent)

        accent = _ACCENT.get(kind, _ACCENT["info"])
        self.setStyleSheet(
            "QLabel {"
            "background: #1f2430; color: #ffffff; padding: 10px 16px;"
            f"border-left: 4px solid {accent}; border-radius: 4px; font-size: 13px;"
            "}"
        )
        self.setWordWrap(True)
        self.setMaximumWidth(420)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.adjustSize()


class NotificationCenter(QObject):
    def __init__(self, window: QMainWindow) -> None:
        super().__init__(window)

        self._window = window
        self._toasts: list[_Toast] = []
        self._busy: dict[int, str] = {}
        self._next_token = 1

        self._busy_label = QLabel("")
        self._busy_bar = QProgressBar()
        self._busy_bar.setRange(0, 0)  # moves without a percentage
        self._busy_bar.setMaximumWidth(120)
        self._busy_bar.setTextVisible(False)

        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(8, 0, 8, 0)
        row.addWidget(self._busy_bar)
        row.addWidget(self._busy_label)
        self._holder = holder
        holder.hide()
        window.statusBar().addWidget(holder, 1)

        window.installEventFilter(self)

    # ------------------------------------------------------------------ messages

    def toast(self, text: str, kind: str = "success") -> None:
        host = self._window.centralWidget() or self._window
        message = _Toast(host, text, kind)
        self._toasts.append(message)

        while len(self._toasts) > _MAXIMUM_TOASTS:
            self._dismiss(self._toasts[0])

        self._place_toasts()
        message.show()
        message.raise_()
        QTimer.singleShot(int(_TOAST_SECONDS * 1000), lambda: self._dismiss(message))

    def _dismiss(self, message: _Toast) -> None:
        if message in self._toasts:
            self._toasts.remove(message)
            message.hide()
            message.deleteLater()
            self._place_toasts()

    def _place_toasts(self) -> None:
        host = self._window.centralWidget() or self._window
        bottom = host.height() - _MARGIN

        for message in reversed(self._toasts):
            message.adjustSize()
            bottom -= message.height()
            message.move(host.width() - message.width() - _MARGIN, bottom)
            bottom -= 8

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if watched is self._window and event.type() == QEvent.Type.Resize:
            self._place_toasts()

        return False

    # ------------------------------------------------------------------ working

    def begin_busy(self, text: str) -> int:
        token = self._next_token
        self._next_token += 1
        self._busy[token] = text
        self._show_busy()

        return token

    def end_busy(self, token: int) -> None:
        self._busy.pop(token, None)
        self._show_busy()

    def _show_busy(self) -> None:
        if not self._busy:
            self._holder.hide()
            self._busy_label.setText("")

            return

        texts = list(self._busy.values())
        extra = f"  (+{len(texts) - 1} more)" if len(texts) > 1 else ""
        self._busy_label.setText(f"{texts[-1]}{extra}")
        self._holder.show()

    @property
    def busy_texts(self) -> list[str]:
        return list(self._busy.values())

    @property
    def toast_texts(self) -> list[str]:
        return [message.text() for message in self._toasts]


_center: NotificationCenter | None = None


def install(center: NotificationCenter | None) -> None:
    global _center
    _center = center


def notify_success(text: str) -> None:
    if _center is not None:
        _center.toast(text, "success")


def notify_info(text: str) -> None:
    if _center is not None:
        _center.toast(text, "info")


def begin_busy(text: str) -> int:
    """Show `text` in the working bar until end_busy(token). 0 when there is no window to show it in."""

    return _center.begin_busy(text) if _center is not None else 0


def end_busy(token: int) -> None:
    if _center is not None and token:
        _center.end_busy(token)
