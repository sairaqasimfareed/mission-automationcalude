from __future__ import annotations

import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.desktop import theme  # noqa: E402
from src.desktop.theme import ThemeMode, apply_theme  # noqa: E402

# GUI-6 (Unified GUI & Release Hardening): a durable WCAG 2.1 AA
# contrast regression guard, not a one-time hand-computed audit. Every
# text/background pairing actually rendered by the real stylesheet
# (theme.py's _build_stylesheet()/_build_palette()) is checked here
# against the live theme.* token values - so a future token edit that
# silently reintroduces a contrast failure (exactly what GUI-6's own
# audit found: TEXT_MUTED, SUCCESS/WARNING/INFO on Light, badge/
# toolbar-active text, selected-text color, button hover text) fails
# this test immediately instead of shipping unnoticed.

_HEX_RE = re.compile(r"^#([0-9A-Fa-f]{6})$")
_RGBA_RE = re.compile(
    r"^rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)$",
)

# WCAG AA for normal-size text (this app's smallest live text, the
# "small-muted" role, is 11px - well under the 18.66px/14pt-bold
# threshold WCAG treats as "large text", so every check here uses the
# stricter 4.5:1 normal-text ratio, never the relaxed 3:1 large-text
# one).
_AA_NORMAL_TEXT = 4.5


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    match = _HEX_RE.match(value)
    if match is None:
        raise ValueError(f"Not a #RRGGBB color: {value!r}")

    packed = match.group(1)
    return (int(packed[0:2], 16), int(packed[2:4], 16), int(packed[4:6], 16))


def _blend_over(rgba: str, background_hex: str) -> tuple[int, int, int]:
    """Flatten a translucent `rgba(r, g, b, a)` color over a solid
    background into an equivalent solid RGB color."""

    match = _RGBA_RE.match(rgba)
    if match is None:
        raise ValueError(f"Not an rgba(...) color: {rgba!r}")

    r, g, b = (int(match.group(i)) for i in (1, 2, 3))
    alpha = float(match.group(4))
    bg_r, bg_g, bg_b = _hex_to_rgb(background_hex)

    return (
        round(r * alpha + bg_r * (1 - alpha)),
        round(g * alpha + bg_g * (1 - alpha)),
        round(b * alpha + bg_b * (1 - alpha)),
    )


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    def linearize(channel: int) -> float:
        c = channel / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (linearize(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(foreground: str, background: str) -> float:
    """WCAG 2.1 contrast ratio between two `#RRGGBB` colors."""

    l1 = _relative_luminance(_hex_to_rgb(foreground))
    l2 = _relative_luminance(_hex_to_rgb(background))
    lighter, darker = max(l1, l2), min(l1, l2)

    return (lighter + 0.05) / (darker + 0.05)


# --- sanity checks on the contrast-math helpers themselves ----------------


def test_contrast_ratio_black_on_white_is_maximal() -> None:
    assert _contrast_ratio("#000000", "#FFFFFF") == pytest.approx(21.0, abs=0.01)


def test_contrast_ratio_identical_colors_is_one() -> None:
    assert _contrast_ratio("#7C5CFC", "#7C5CFC") == pytest.approx(1.0, abs=0.001)


def test_contrast_ratio_is_symmetric() -> None:
    assert _contrast_ratio("#333333", "#EEEEEE") == pytest.approx(
        _contrast_ratio("#EEEEEE", "#333333"), abs=0.001
    )


def test_blend_over_opaque_color_ignores_the_background() -> None:
    assert _blend_over("rgba(10, 20, 30, 1.0)", "#FFFFFF") == (10, 20, 30)


def test_blend_over_fully_transparent_color_is_the_background() -> None:
    assert _blend_over("rgba(10, 20, 30, 0.0)", "#ABCDEF") == _hex_to_rgb("#ABCDEF")


# --- the real audit ---------------------------------------------------------


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])

    yield app  # type: ignore[misc]


@pytest.fixture(autouse=False)
def _restore_dark_theme(qapp: QApplication) -> Iterator[None]:
    try:
        yield
    finally:
        apply_theme(qapp, ThemeMode.DARK)


_SURFACE_TOKENS = ("BG_WINDOW", "BG_SURFACE", "BG_ELEVATED")
_BODY_TEXT_TOKENS = ("TEXT_PRIMARY", "TEXT_SECONDARY", "TEXT_MUTED")
_SEMANTIC_TOKENS = ("SUCCESS", "WARNING", "ERROR", "INFO")


@pytest.mark.parametrize("mode", [ThemeMode.DARK, ThemeMode.LIGHT])
@pytest.mark.parametrize("surface_token", _SURFACE_TOKENS)
@pytest.mark.parametrize("text_token", _BODY_TEXT_TOKENS)
def test_body_text_meets_aa_on_every_surface(
    qapp: QApplication,
    _restore_dark_theme: None,
    mode: ThemeMode,
    surface_token: str,
    text_token: str,
) -> None:
    """TEXT_PRIMARY/SECONDARY/MUTED all appear directly on any of the
    three surface backgrounds (QLabel's default background is
    transparent, so it shows whatever card/window/input surface is
    behind it) - real, live pairings, not hypothetical ones."""

    apply_theme(qapp, mode)

    text_color = getattr(theme, text_token)
    surface_color = getattr(theme, surface_token)

    ratio = _contrast_ratio(text_color, surface_color)

    assert ratio >= _AA_NORMAL_TEXT, (
        f"{mode.value}: {text_token} ({text_color}) on {surface_token} "
        f"({surface_color}) = {ratio:.2f}, below WCAG AA's {_AA_NORMAL_TEXT}"
    )


@pytest.mark.parametrize("mode", [ThemeMode.DARK, ThemeMode.LIGHT])
@pytest.mark.parametrize("surface_token", _SURFACE_TOKENS)
@pytest.mark.parametrize("semantic_token", _SEMANTIC_TOKENS)
def test_semantic_status_text_meets_aa_on_every_surface(
    qapp: QApplication,
    _restore_dark_theme: None,
    mode: ThemeMode,
    surface_token: str,
    semantic_token: str,
) -> None:
    """role="success"/"warning"/"error" QLabels render directly on
    whatever surface they sit on - QualityCenterView/ContentStudioView
    place these on cards (BG_SURFACE), the window, and elevated
    panels alike."""

    apply_theme(qapp, mode)

    semantic_color = getattr(theme, semantic_token)
    surface_color = getattr(theme, surface_token)

    ratio = _contrast_ratio(semantic_color, surface_color)

    assert ratio >= _AA_NORMAL_TEXT, (
        f"{mode.value}: {semantic_token} ({semantic_color}) on "
        f"{surface_token} ({surface_color}) = {ratio:.2f}, below AA"
    )


@pytest.mark.parametrize("mode", [ThemeMode.DARK, ThemeMode.LIGHT])
def test_primary_button_text_meets_aa_in_every_visual_state(
    qapp: QApplication, _restore_dark_theme: None, mode: ThemeMode
) -> None:
    """QPushButton[variant="primary"] always renders white text -
    default/hover/pressed all use a different background (ACCENT/
    ACCENT_HOVER/ACCENT_PRESSED respectively)."""

    apply_theme(qapp, mode)

    for background_token in ("ACCENT", "ACCENT_HOVER", "ACCENT_PRESSED"):
        background_color = getattr(theme, background_token)
        ratio = _contrast_ratio("#FFFFFF", background_color)

        assert ratio >= _AA_NORMAL_TEXT, (
            f"{mode.value}: white button text on {background_token} "
            f"({background_color}) = {ratio:.2f}, below AA"
        )


@pytest.mark.parametrize("mode", [ThemeMode.DARK, ThemeMode.LIGHT])
def test_selected_text_meets_aa_against_the_highlight_color(
    qapp: QApplication, _restore_dark_theme: None, mode: ThemeMode
) -> None:
    """The QPalette HighlightedText/Highlight pair is what a user
    actually sees when selecting text in a QLineEdit."""

    apply_theme(qapp, mode)

    ratio = _contrast_ratio("#FFFFFF", theme.ACCENT)

    assert ratio >= _AA_NORMAL_TEXT, (
        f"{mode.value}: selected-text white on Highlight ACCENT "
        f"({theme.ACCENT}) = {ratio:.2f}, below AA"
    )


@pytest.mark.parametrize("mode", [ThemeMode.DARK, ThemeMode.LIGHT])
@pytest.mark.parametrize("surface_token", _SURFACE_TOKENS)
def test_badge_and_active_toolbar_text_meets_aa(
    qapp: QApplication,
    _restore_dark_theme: None,
    mode: ThemeMode,
    surface_token: str,
) -> None:
    """QLabel[role="badge"] and QToolButton:pressed/checked both
    render ACCENT_ON_SOFT text on an ACCENT_SOFT translucent
    background - flatten the translucency over each real surface
    token before checking (a badge can sit on any of the three)."""

    apply_theme(qapp, mode)

    surface_color = getattr(theme, surface_token)
    blended_rgb = _blend_over(theme.ACCENT_SOFT, surface_color)
    blended_hex = "#{:02X}{:02X}{:02X}".format(*blended_rgb)

    ratio = _contrast_ratio(theme.ACCENT_ON_SOFT, blended_hex)

    assert ratio >= _AA_NORMAL_TEXT, (
        f"{mode.value}: ACCENT_ON_SOFT ({theme.ACCENT_ON_SOFT}) on "
        f"ACCENT_SOFT over {surface_token} (blended {blended_hex}) "
        f"= {ratio:.2f}, below AA"
    )


# --- keyboard-focus visibility ---------------------------------------------


@pytest.mark.parametrize("mode", [ThemeMode.DARK, ThemeMode.LIGHT])
def test_buttons_have_a_visible_keyboard_focus_indicator(
    qapp: QApplication, _restore_dark_theme: None, mode: ThemeMode
) -> None:
    """
    GUI-6: once QPushButton/QToolButton carry any QSS border rule,
    Fusion's native dashed keyboard-focus rectangle stops rendering
    reliably - there was no visible way to tell which button had
    keyboard focus at all. Checks that an explicit, accent-colored
    :focus rule actually exists in the built stylesheet and is wired
    to the theme's own current ACCENT value (not a stale/hardcoded
    color that would drift from a future palette change).
    """

    apply_theme(qapp, mode)
    stylesheet = qapp.styleSheet()

    assert "QPushButton:focus" in stylesheet
    assert "QToolButton:focus" in stylesheet

    # The rule body immediately following each selector should
    # reference the *current* ACCENT value, not a color left behind
    # from a different theme.
    push_button_focus_index = stylesheet.index("QPushButton:focus")
    push_button_focus_body = stylesheet[
        push_button_focus_index : push_button_focus_index + 200
    ]
    assert theme.ACCENT in push_button_focus_body

    tool_button_focus_index = stylesheet.index("QToolButton:focus")
    tool_button_focus_body = stylesheet[
        tool_button_focus_index : tool_button_focus_index + 200
    ]
    assert theme.ACCENT in tool_button_focus_body
