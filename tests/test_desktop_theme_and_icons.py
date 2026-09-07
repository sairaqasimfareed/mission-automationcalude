from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.desktop.icons import _ICONS, app_icon, icon  # noqa: E402
from src.desktop.theme import apply_theme  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])

    yield app  # type: ignore[misc]


def test_apply_theme_does_not_raise(qapp: QApplication) -> None:
    apply_theme(qapp)

    assert qapp.styleSheet()


def test_palette_gives_button_text_a_visible_color(qapp: QApplication) -> None:
    """
    Real-world finding, in two parts. First: this app had no QPalette
    override at all, only a QSS stylesheet - Fusion draws several
    elements (a QComboBox's drop-down arrow being the concrete case a
    user actually hit) from QPalette colors rather than through QSS,
    so with no override that meant Qt's own default (light-theme)
    palette, rendering the arrow glyph invisibly dark against this
    app's QSS-dark background - a genuinely functional dropdown (e.g.
    Provider Manager's "Provider name") looked indistinguishable from
    a plain text field, and clicking its text area just placed a
    cursor rather than opening the list.

    Second: an attempted QSS-only fix (a custom SVG image for
    QComboBox::down-arrow) turned out not to render at all in the real
    app either, confirmed by the same symptom persisting - not worth
    depending on SVG/data-URI support in Qt's QSS engine when the
    real, robust fix is giving Fusion's own native arrow-drawing a
    palette it can actually use.
    """

    from PySide6.QtGui import QPalette

    from src.desktop.theme import TEXT_SECONDARY, _build_palette

    palette = _build_palette()
    button_text = palette.color(QPalette.ColorRole.ButtonText)

    assert button_text.name().lower() == TEXT_SECONDARY.lower()


def test_apply_theme_sets_a_real_palette_not_just_a_stylesheet(
    qapp: QApplication,
) -> None:
    apply_theme(qapp)

    from PySide6.QtGui import QPalette

    from src.desktop.theme import TEXT_SECONDARY

    button_text = qapp.palette().color(QPalette.ColorRole.ButtonText)
    assert button_text.name().lower() == TEXT_SECONDARY.lower()


@pytest.mark.parametrize("name", sorted(_ICONS))
def test_every_defined_icon_renders(qapp: QApplication, name: str) -> None:
    result = icon(name)

    assert not result.isNull()


def test_unknown_icon_name_raises(qapp: QApplication) -> None:
    with pytest.raises(KeyError):
        icon("does-not-exist")


def test_app_icon_has_multiple_sizes(qapp: QApplication) -> None:
    result = app_icon()

    assert not result.isNull()
    assert len(result.availableSizes()) >= 5
