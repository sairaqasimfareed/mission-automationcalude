from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from src.desktop import widgets  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])

    yield app  # type: ignore[misc]


# Real-world finding, 2026-09-17: QLabel defaults to non-selectable
# text, and every text label in this app is built through these
# helpers (confirmed via grep: nothing outside widgets.py calls
# QLabel(text) directly) - so no label anywhere could be selected or
# copied. Each helper must now enable mouse-selectable text.
def test_heading_text_is_selectable(qapp: QApplication) -> None:
    label = widgets.heading("Title")

    assert bool(
        label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse
    )


def test_subheading_text_is_selectable(qapp: QApplication) -> None:
    label = widgets.subheading("Subtitle")

    assert bool(
        label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse
    )


def test_muted_text_is_selectable(qapp: QApplication) -> None:
    label = widgets.muted("Muted detail text")

    assert bool(
        label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse
    )


def test_small_muted_text_is_selectable(qapp: QApplication) -> None:
    label = widgets.small_muted("Small muted detail text")

    assert bool(
        label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse
    )


def test_status_label_text_is_selectable(qapp: QApplication) -> None:
    label = widgets.status_label("Ready", role="success")

    assert bool(
        label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse
    )


def test_badge_text_is_selectable(qapp: QApplication) -> None:
    label = widgets.badge("premium")

    assert bool(
        label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse
    )


def test_card_title_text_is_selectable(qapp: QApplication) -> None:
    """
    card() builds its title through subheading() rather than a raw
    QLabel - confirms the fix reaches composed widgets too, not just
    the direct helpers.
    """

    _frame, _layout = widgets.card("Card Title")

    title_label = _frame.findChild(QLabel)

    assert title_label is not None

    assert bool(
        title_label.textInteractionFlags()
        & Qt.TextInteractionFlag.TextSelectableByMouse
    )
