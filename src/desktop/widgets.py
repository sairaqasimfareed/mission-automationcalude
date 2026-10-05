from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.desktop import theme
from src.desktop.icons import icon
from src.desktop.theme import SPACE_LG, SPACE_MD, SPACE_SM

# Spacing tokens are theme-invariant (fine to import by name once);
# TEXT_PRIMARY is not - read as `theme.TEXT_PRIMARY` below so a live
# theme switch (GUI-1) is picked up, matching icons.py's own approach.

# Shared widget builders so every desktop view assembles the same
# visual language (card shape, heading scale, button variants)
# instead of each view re-implementing its own layout conventions.

# Real-world finding, 2026-09-17: QLabel defaults to non-selectable
# text, and every text label in this app is built through the helpers
# below (nothing outside this file calls QLabel(text) directly) - so
# no label anywhere could be selected or copied. Applying this one
# flag here fixes it app-wide instead of touching every view.
_SELECTABLE_TEXT = Qt.TextInteractionFlag.TextSelectableByMouse


def heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "heading")
    label.setTextInteractionFlags(_SELECTABLE_TEXT)

    return label


def subheading(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "subheading")
    label.setTextInteractionFlags(_SELECTABLE_TEXT)

    return label


def muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "muted")
    label.setWordWrap(True)
    label.setTextInteractionFlags(_SELECTABLE_TEXT)

    return label


def small_muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "small-muted")
    label.setWordWrap(True)
    label.setTextInteractionFlags(_SELECTABLE_TEXT)

    return label


def status_label(text: str, *, role: str) -> QLabel:
    """role is one of: success, warning, error."""

    label = QLabel(text)
    label.setProperty("role", role)
    label.setWordWrap(True)
    label.setTextInteractionFlags(_SELECTABLE_TEXT)

    return label


def badge(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "badge")
    label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    label.setTextInteractionFlags(_SELECTABLE_TEXT)

    return label


def separator() -> QFrame:
    line = QFrame()
    line.setProperty("separator", True)
    line.setFrameShape(QFrame.Shape.NoFrame)

    return line


def card(
    title: str,
    *,
    icon_name: str | None = None,
    header_widget: QWidget | None = None,
) -> tuple[QFrame, QVBoxLayout]:
    """
    Build one bordered card with a title row.

    Returns the frame (add it to a parent layout) and the inner
    layout (add the card's own content to that).

    header_widget, when given, is placed at the far right of the title
    row (after the stretch) - e.g. a collapse/expand toggle for a card
    whose full content can get tall (ProjectWorkspaceView's own
    "Project status" card).
    """

    frame = QFrame()
    frame.setProperty("card", True)

    layout = QVBoxLayout(frame)
    layout.setContentsMargins(SPACE_LG, SPACE_LG, SPACE_LG, SPACE_LG)
    layout.setSpacing(SPACE_SM)

    header = QHBoxLayout()
    header.setSpacing(SPACE_SM)

    if icon_name is not None:
        icon_label = QLabel()
        icon_label.setPixmap(
            icon(icon_name, color=theme.TEXT_PRIMARY, size=17).pixmap(QSize(17, 17))
        )
        header.addWidget(icon_label)

    header.addWidget(subheading(title))
    header.addStretch()

    if header_widget is not None:
        header.addWidget(header_widget)

    layout.addLayout(header)

    return frame, layout


def button(
    text: str,
    *,
    variant: str | None = None,
    icon_name: str | None = None,
) -> QPushButton:
    """variant is one of: primary, ghost, danger, or None for default."""

    widget = QPushButton(text)

    if variant is not None:
        widget.setProperty("variant", variant)

    if icon_name is not None:
        widget.setIcon(icon(icon_name, color=theme.TEXT_PRIMARY, size=16))
        widget.setIconSize(QSize(16, 16))

    return widget


def row(*widgets: QWidget, stretch_at_end: bool = True) -> QHBoxLayout:
    layout = QHBoxLayout()
    layout.setSpacing(SPACE_MD)

    for widget in widgets:
        layout.addWidget(widget)

    if stretch_at_end:
        layout.addStretch()

    return layout


class ExpandableList(QWidget):
    """
    A list that shows its first `visible_count` rows and keeps the rest behind a
    "Show all N" button - so a screen that lists one row per scene stays short
    for a 100-scene project instead of becoming a very long scroll.

    Expanding only shows or hides rows that already exist: nothing is rebuilt,
    so the page does not jump back to the top (the failure the Content Studio
    had when a refresh rebuilt its widgets). The expanded state is a view detail
    and resets on the next refresh.
    """

    def __init__(
        self,
        rows: list[QWidget],
        *,
        visible_count: int,
        noun: str,
    ) -> None:
        super().__init__()

        self._rows = rows
        self._visible_count = max(visible_count, 0)
        self._noun = noun
        self._expanded = False
        self._toggle: QPushButton | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_SM)

        for row_widget in rows:
            layout.addWidget(row_widget)

        if len(rows) > self._visible_count:
            self._toggle = button("", variant="ghost")
            self._toggle.clicked.connect(self._handle_toggle)
            layout.addWidget(self._toggle, alignment=Qt.AlignmentFlag.AlignLeft)

        self._apply()

    @property
    def is_expanded(self) -> bool:
        return self._expanded

    @property
    def hidden_count(self) -> int:
        return (
            max(len(self._rows) - self._visible_count, 0) if not self._expanded else 0
        )

    @property
    def toggle_button(self) -> QPushButton | None:
        return self._toggle

    def _handle_toggle(self) -> None:
        self._expanded = not self._expanded
        self._apply()

    def _apply(self) -> None:
        for index, row_widget in enumerate(self._rows):
            row_widget.setHidden(not self._expanded and index >= self._visible_count)

        if self._toggle is not None:
            total = len(self._rows)
            self._toggle.setText(
                "Show fewer"
                if self._expanded
                else f"Show all {total} {self._noun} "
                f"({total - self._visible_count} more)"
            )
