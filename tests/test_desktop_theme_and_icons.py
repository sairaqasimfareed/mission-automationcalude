from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.desktop import theme  # noqa: E402
from src.desktop.icons import _ICONS, app_icon, icon  # noqa: E402
from src.desktop.theme import ThemeMode, apply_theme  # noqa: E402


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


# GUI-1: Light/System theme -------------------------------------------------


@pytest.fixture(autouse=False)
def _restore_dark_theme(qapp: QApplication) -> Iterator[None]:
    """
    Every test below mutates the process-wide theme state apply_theme()
    maintains (module-level color tokens, current_resolved_mode()).
    Restoring DARK afterward keeps this file's other, theme-agnostic
    tests (and any test file that happens to run later in the same
    process) from observing a LIGHT theme left behind by an earlier
    test - qapp is a module-scoped, shared QApplication, not a fresh
    one per test.
    """

    try:
        yield
    finally:
        apply_theme(qapp, ThemeMode.DARK)


class _FakeStyleHints:
    def __init__(self, color_scheme: Qt.ColorScheme) -> None:
        self._color_scheme = color_scheme

    def colorScheme(self) -> Qt.ColorScheme:
        return self._color_scheme


class _FakeApp:
    """A minimal stand-in for QApplication, for resolve_theme_mode()
    unit tests that only need `.styleHints().colorScheme()` - avoids
    depending on the real, possibly-offscreen-ambiguous system color
    scheme to test SYSTEM resolution's own branching logic."""

    def __init__(self, color_scheme: Qt.ColorScheme) -> None:
        self._style_hints = _FakeStyleHints(color_scheme)

    def styleHints(self) -> _FakeStyleHints:
        return self._style_hints


@pytest.mark.parametrize(
    ("color_scheme", "expected"),
    [
        (Qt.ColorScheme.Light, ThemeMode.LIGHT),
        (Qt.ColorScheme.Dark, ThemeMode.DARK),
        (Qt.ColorScheme.Unknown, ThemeMode.DARK),
    ],
)
def test_resolve_theme_mode_system_follows_qt_color_scheme(
    color_scheme: Qt.ColorScheme, expected: ThemeMode
) -> None:
    from src.desktop.theme import resolve_theme_mode

    fake_app = _FakeApp(color_scheme)

    assert resolve_theme_mode(fake_app, ThemeMode.SYSTEM) == expected  # type: ignore[arg-type]


@pytest.mark.parametrize("mode", [ThemeMode.LIGHT, ThemeMode.DARK])
def test_resolve_theme_mode_is_a_no_op_for_an_explicit_mode(mode: ThemeMode) -> None:
    from src.desktop.theme import resolve_theme_mode

    # An explicit LIGHT/DARK preference is never overridden by the
    # system color scheme - the fake app here reports the *opposite*
    # scheme to prove that.
    opposite = Qt.ColorScheme.Dark if mode is ThemeMode.LIGHT else Qt.ColorScheme.Light
    fake_app = _FakeApp(opposite)

    assert resolve_theme_mode(fake_app, mode) == mode  # type: ignore[arg-type]


def test_apply_theme_returns_the_resolved_mode(
    qapp: QApplication, _restore_dark_theme: None
) -> None:
    assert apply_theme(qapp, ThemeMode.LIGHT) == ThemeMode.LIGHT
    assert apply_theme(qapp, ThemeMode.DARK) == ThemeMode.DARK


def test_apply_theme_tracks_the_currently_resolved_mode(
    qapp: QApplication, _restore_dark_theme: None
) -> None:
    from src.desktop.theme import current_resolved_mode

    apply_theme(qapp, ThemeMode.LIGHT)
    assert current_resolved_mode() == ThemeMode.LIGHT

    apply_theme(qapp, ThemeMode.DARK)
    assert current_resolved_mode() == ThemeMode.DARK


def test_light_and_dark_themes_use_genuinely_different_color_tokens(
    qapp: QApplication, _restore_dark_theme: None
) -> None:
    """
    Not a naive inversion check - just confirms LIGHT and DARK don't
    silently collapse to the same values (e.g. a copy-paste bug in
    _LIGHT_TOKENS reusing _DARK_TOKENS unchanged).
    """

    apply_theme(qapp, ThemeMode.DARK)
    dark_window = theme.BG_WINDOW
    dark_accent = theme.ACCENT

    apply_theme(qapp, ThemeMode.LIGHT)
    light_window = theme.BG_WINDOW
    light_accent = theme.ACCENT

    assert dark_window != light_window
    assert dark_accent != light_accent
    assert light_window.upper() == "#F5F6FA"
    assert dark_window.upper() == "#12141A"


@pytest.mark.parametrize("mode", [ThemeMode.DARK, ThemeMode.LIGHT])
def test_icons_re_theme_live_after_apply_theme_switches_mode(
    qapp: QApplication, _restore_dark_theme: None, mode: ThemeMode
) -> None:
    """
    The real regression this locks in: icons.py used to bind ACCENT/
    TEXT_PRIMARY/TEXT_SECONDARY once at import time (`from
    src.desktop.theme import ...`), so a live theme switch would leave
    every icon rendered in whatever theme was active when icons.py was
    first imported - almost always DARK, since that happens very early
    in app startup. Fixed by reading `theme.TEXT_SECONDARY` at call
    time instead. This renders a real icon under each theme and checks
    the actual most-common opaque pixel color matches that theme's
    current TEXT_SECONDARY - not just that the token value changed.
    """

    from PySide6.QtGui import QColor

    apply_theme(qapp, mode)
    expected = QColor(theme.TEXT_SECONDARY)

    rendered = icon("dashboard", size=24).pixmap(24, 24).toImage()

    # Count fully-opaque pixels within a small tolerance of the
    # expected stroke color, rather than requiring an exact hex match
    # - SVG antialiasing blends a handful of edge pixels by +/-1 on a
    # single channel even along an otherwise-solid straight stroke.
    matching_pixels = 0
    for x in range(rendered.width()):
        for y in range(rendered.height()):
            pixel = rendered.pixelColor(x, y)
            if pixel.alpha() <= 200:
                continue
            if (
                abs(pixel.red() - expected.red()) <= 2
                and abs(pixel.green() - expected.green()) <= 2
                and abs(pixel.blue() - expected.blue()) <= 2
            ):
                matching_pixels += 1

    # The rendered icon has a real, solid stroke in this color - not
    # just one or two stray antialiased pixels that happen to be close.
    assert matching_pixels > 20
