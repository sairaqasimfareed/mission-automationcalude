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


def test_combo_box_down_arrow_has_an_explicit_visible_color() -> None:
    """
    Real-world finding: QComboBox::drop-down had its border/background
    stripped for the dark theme, but QComboBox::down-arrow was never
    given an explicit color - Qt's default arrow glyph rendered too
    dark to see against this app's dark background, making a
    genuinely functional dropdown (e.g. Provider Manager's "Provider
    name") look indistinguishable from a plain text field.
    """

    from src.desktop.theme import TEXT_SECONDARY, _build_stylesheet

    css = _build_stylesheet()
    arrow_rule_index = css.find("QComboBox::down-arrow")

    assert arrow_rule_index != -1
    arrow_rule = css[arrow_rule_index : arrow_rule_index + 400]
    assert "image:" in arrow_rule
    assert TEXT_SECONDARY[1:] in arrow_rule


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
