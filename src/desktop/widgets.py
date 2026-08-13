from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.desktop.icons import icon
from src.desktop.theme import SPACE_LG, SPACE_MD, SPACE_SM, TEXT_PRIMARY

# Shared widget builders so every desktop view assembles the same
# visual language (card shape, heading scale, button variants)
# instead of each view re-implementing its own layout conventions.


def heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "heading")

    return label


def subheading(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "subheading")

    return label


def muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "muted")
    label.setWordWrap(True)

    return label


def small_muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "small-muted")
    label.setWordWrap(True)

    return label


def status_label(text: str, *, role: str) -> QLabel:
    """role is one of: success, warning, error."""

    label = QLabel(text)
    label.setProperty("role", role)
    label.setWordWrap(True)

    return label


def badge(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "badge")
    label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    return label


def separator() -> QFrame:
    line = QFrame()
    line.setProperty("separator", True)
    line.setFrameShape(QFrame.Shape.NoFrame)

    return line


def card(title: str, *, icon_name: str | None = None) -> tuple[QFrame, QVBoxLayout]:
    """
    Build one bordered card with a title row.

    Returns the frame (add it to a parent layout) and the inner
    layout (add the card's own content to that).
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
            icon(icon_name, color=TEXT_PRIMARY, size=17).pixmap(QSize(17, 17))
        )
        header.addWidget(icon_label)

    header.addWidget(subheading(title))
    header.addStretch()

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
        icon_color = TEXT_PRIMARY
        widget.setIcon(icon(icon_name, color=icon_color, size=16))
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
