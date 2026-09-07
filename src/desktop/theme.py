from __future__ import annotations

from enum import Enum

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

# Two cinematic, purpose-built palettes - a video-production tool
# spends most of its life next to a real editor/preview, so both
# themes lean toward a calm, desaturated surface that gets out of the
# way of footage rather than competing with it. Dark was this app's
# only option until GUI-1 (Unified GUI & Release Hardening); Light is
# a deliberately separate design, not a naive color inversion - the
# accent shifts to a deeper violet and every semantic color (success/
# warning/error/info) shifts to a more saturated, higher-contrast
# variant, since the pastel-bright dark-theme versions read as washed
# out against a white surface.


class ThemeMode(str, Enum):
    """A user-selectable theme preference, persisted across restarts."""

    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"


_DARK_TOKENS: dict[str, str] = {
    "BG_WINDOW": "#12141A",
    "BG_SURFACE": "#1B1E27",
    "BG_SURFACE_ALT": "#20232E",
    "BG_ELEVATED": "#262A36",
    "BORDER": "#2E3340",
    "BORDER_STRONG": "#3A4050",
    "TEXT_PRIMARY": "#F3F4F7",
    "TEXT_SECONDARY": "#A6ACBA",
    "TEXT_MUTED": "#6B7280",
    "ACCENT": "#7C5CFC",
    "ACCENT_HOVER": "#8F72FF",
    "ACCENT_PRESSED": "#6647E0",
    "ACCENT_SOFT": "rgba(124, 92, 252, 0.18)",
    "ACCENT_SOFT_STRONG": "rgba(124, 92, 252, 0.32)",
    "SUCCESS": "#3DD68C",
    "WARNING": "#F5A623",
    "ERROR": "#FF5C6C",
    "INFO": "#4EA1F3",
}

_LIGHT_TOKENS: dict[str, str] = {
    "BG_WINDOW": "#F5F6FA",
    "BG_SURFACE": "#FFFFFF",
    "BG_SURFACE_ALT": "#EEF0F5",
    "BG_ELEVATED": "#FFFFFF",
    "BORDER": "#D8DBE3",
    "BORDER_STRONG": "#C0C4D0",
    "TEXT_PRIMARY": "#1B1E27",
    "TEXT_SECONDARY": "#585F70",
    "TEXT_MUTED": "#8B92A3",
    "ACCENT": "#6647E0",
    "ACCENT_HOVER": "#7C5CFC",
    "ACCENT_PRESSED": "#5535C4",
    "ACCENT_SOFT": "rgba(102, 71, 224, 0.10)",
    "ACCENT_SOFT_STRONG": "rgba(102, 71, 224, 0.20)",
    "SUCCESS": "#1E9E63",
    "WARNING": "#B9740A",
    "ERROR": "#D3273D",
    "INFO": "#2A72C7",
}

_TOKENS_BY_RESOLVED_MODE: dict[ThemeMode, dict[str, str]] = {
    ThemeMode.DARK: _DARK_TOKENS,
    ThemeMode.LIGHT: _LIGHT_TOKENS,
}

# Color token module attributes - kept as plain module-level names for
# backward compatibility (existing call sites read them as
# `theme.ACCENT` etc.), but reassigned by apply_theme() below rather
# than fixed at import time. Two other modules (icons.py, widgets.py)
# deliberately read these via `from src.desktop import theme;
# theme.ACCENT` (a live module-attribute lookup at call time) instead
# of `from src.desktop.theme import ACCENT` (a name copied once at
# import time) specifically so a theme switch is visible to them
# immediately, without either module needing its own theme-mode logic.
BG_WINDOW = _DARK_TOKENS["BG_WINDOW"]
BG_SURFACE = _DARK_TOKENS["BG_SURFACE"]
BG_SURFACE_ALT = _DARK_TOKENS["BG_SURFACE_ALT"]
BG_ELEVATED = _DARK_TOKENS["BG_ELEVATED"]

BORDER = _DARK_TOKENS["BORDER"]
BORDER_STRONG = _DARK_TOKENS["BORDER_STRONG"]

TEXT_PRIMARY = _DARK_TOKENS["TEXT_PRIMARY"]
TEXT_SECONDARY = _DARK_TOKENS["TEXT_SECONDARY"]
TEXT_MUTED = _DARK_TOKENS["TEXT_MUTED"]

ACCENT = _DARK_TOKENS["ACCENT"]
ACCENT_HOVER = _DARK_TOKENS["ACCENT_HOVER"]
ACCENT_PRESSED = _DARK_TOKENS["ACCENT_PRESSED"]
ACCENT_SOFT = _DARK_TOKENS["ACCENT_SOFT"]
ACCENT_SOFT_STRONG = _DARK_TOKENS["ACCENT_SOFT_STRONG"]

SUCCESS = _DARK_TOKENS["SUCCESS"]
WARNING = _DARK_TOKENS["WARNING"]
ERROR = _DARK_TOKENS["ERROR"]
INFO = _DARK_TOKENS["INFO"]

# Theme-invariant: spacing/type scale never change between palettes.
FONT_FAMILY = "Segoe UI"

SIZE_H1 = 20
SIZE_H2 = 14
SIZE_BODY = 13
SIZE_SMALL = 11

SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 24

RADIUS = 10
RADIUS_SM = 6

_current_resolved_mode: ThemeMode = ThemeMode.DARK


def current_resolved_mode() -> ThemeMode:
    """The theme actually in effect right now (never SYSTEM)."""

    return _current_resolved_mode


def resolve_theme_mode(app: QApplication, mode: ThemeMode) -> ThemeMode:
    """
    Resolve a user preference to a concrete LIGHT/DARK theme.

    SYSTEM defers to Qt's own `QStyleHints.colorScheme()` (the real,
    OS-level light/dark signal, available since Qt 6.5 - confirmed
    present in this project's pinned PySide6 6.11). A genuinely
    unknown OS report (`Qt.ColorScheme.Unknown`, e.g. an older Windows
    build with no light/dark preference exposed) falls back to DARK,
    this app's long-standing, already-proven default, rather than
    guessing LIGHT.
    """

    if mode is not ThemeMode.SYSTEM:
        return mode

    color_scheme = app.styleHints().colorScheme()

    if color_scheme == Qt.ColorScheme.Light:
        return ThemeMode.LIGHT

    return ThemeMode.DARK


def apply_theme(app: QApplication, mode: ThemeMode = ThemeMode.SYSTEM) -> ThemeMode:
    """Apply the shared font, palette, and stylesheet to the whole
    application, resolving `mode` (SYSTEM/LIGHT/DARK) to a concrete
    theme first. Returns the resolved mode actually applied.

    Explicitly selects the "Fusion" style before applying anything
    else - found via user report: on Windows, the default native
    ("windowsvista") style only partially honors QSS colors on
    QLineEdit/QComboBox, painting its own light native frame under the
    QSS-declared text color and producing near-invisible pale-on-pale
    text. Fusion is the one built-in Qt style that fully respects
    QSS-declared colors on every widget, so a theme actually renders
    as designed instead of half-applying.

    Also sets a real QPalette, not stylesheet colors alone - real-
    world finding: this app originally had no QPalette override at
    all, only the QSS stylesheet below. QSS colors a widget's own
    background/text, but several elements Fusion draws NATIVELY rather
    than through QSS (a QComboBox's drop-down arrow being the concrete
    case a user actually hit) are painted from QPalette colors instead
    - with no override, that meant Qt's own default (light-theme)
    palette, rendering a dark arrow glyph invisibly against this app's
    then-dark-only QSS background.

    Safe to call again after startup (e.g. the user changes their
    theme preference in Settings) - palette, stylesheet, and every
    QSS-role-driven widget re-color immediately. Icons and any other
    QIcon/QPixmap already baked into an existing QAction/QPushButton
    do not self-refresh (Qt has no live-recolor hook for an already-
    constructed QIcon) - the caller is expected to tell the user a
    restart is recommended for those to fully catch up, matching this
    function's own doc rather than silently mismatching name and
    behavior.
    """

    global _current_resolved_mode

    resolved = resolve_theme_mode(app, mode)
    _current_resolved_mode = resolved

    _apply_tokens(_TOKENS_BY_RESOLVED_MODE[resolved])

    if (
        "Fusion" in QStyleFactory.keys()
    ):  # noqa: SIM118 - QStyleFactory.keys() is not a dict
        app.setStyle(QStyleFactory.create("Fusion"))

    app.setPalette(_build_palette())

    font = QFont(FONT_FAMILY, SIZE_BODY)
    app.setFont(font)
    app.setStyleSheet(_build_stylesheet())

    return resolved


def _apply_tokens(tokens: dict[str, str]) -> None:
    """Repoint every color-token module attribute to `tokens`."""

    module_globals = globals()

    for key, value in tokens.items():
        module_globals[key] = value


def _build_palette() -> QPalette:
    palette = QPalette()

    palette.setColor(QPalette.ColorRole.Window, QColor(BG_WINDOW))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Base, QColor(BG_ELEVATED))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(BG_SURFACE_ALT))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Button, QColor(BG_ELEVATED))
    # ButtonText specifically is what Fusion's native combo-box
    # drop-down arrow is drawn with - this is the one color that
    # actually fixes the real, reported invisible-arrow bug.
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT_SECONDARY))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(BG_ELEVATED))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(TEXT_MUTED))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Link, QColor(ACCENT))

    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.WindowText,
        QColor(TEXT_MUTED),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(TEXT_MUTED)
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.ButtonText,
        QColor(TEXT_MUTED),
    )

    return palette


def _build_stylesheet() -> str:
    return f"""
    QMainWindow, QWidget {{
        background: {BG_WINDOW};
        color: {TEXT_PRIMARY};
        font-family: "{FONT_FAMILY}";
        font-size: {SIZE_BODY}px;
    }}

    QScrollArea {{
        background: transparent;
        border: none;
    }}

    QScrollArea > QWidget > QWidget {{
        background: transparent;
    }}

    QLabel {{
        background: transparent;
        color: {TEXT_PRIMARY};
    }}

    QLabel[role="heading"] {{
        font-size: {SIZE_H1}px;
        font-weight: 600;
        color: {TEXT_PRIMARY};
    }}

    QLabel[role="subheading"] {{
        font-size: {SIZE_H2}px;
        font-weight: 600;
        color: {TEXT_PRIMARY};
    }}

    QLabel[role="muted"] {{
        color: {TEXT_SECONDARY};
    }}

    QLabel[role="small-muted"] {{
        color: {TEXT_MUTED};
        font-size: {SIZE_SMALL}px;
    }}

    QLabel[role="success"] {{
        color: {SUCCESS};
        font-weight: 600;
    }}

    QLabel[role="warning"] {{
        color: {WARNING};
    }}

    QLabel[role="error"] {{
        color: {ERROR};
        font-weight: 600;
    }}

    QLabel[role="badge"] {{
        background: {ACCENT_SOFT};
        color: {ACCENT_HOVER};
        border-radius: {RADIUS_SM}px;
        padding: 2px {SPACE_SM}px;
        font-size: {SIZE_SMALL}px;
        font-weight: 600;
    }}

    QFrame[card="true"] {{
        background: {BG_SURFACE};
        border: 1px solid {BORDER};
        border-radius: {RADIUS}px;
    }}

    QFrame[card="true"]:hover {{
        border: 1px solid {BORDER_STRONG};
    }}

    QFrame[sceneRow="true"] {{
        background: {BG_SURFACE_ALT};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_SM}px;
    }}

    QFrame[separator="true"] {{
        background: {BORDER};
        max-height: 1px;
        min-height: 1px;
        border: none;
    }}

    QProgressBar {{
        background: {BG_SURFACE_ALT};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_SM}px;
        text-align: center;
        color: {TEXT_SECONDARY};
        min-height: 18px;
    }}

    QProgressBar::chunk {{
        background: {ACCENT};
        border-radius: {RADIUS_SM}px;
    }}

    QPushButton {{
        background: {BG_ELEVATED};
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER_STRONG};
        border-radius: {RADIUS_SM}px;
        padding: 7px {SPACE_LG}px;
    }}

    QPushButton:hover {{
        background: {BORDER_STRONG};
    }}

    QPushButton:pressed {{
        background: {BG_SURFACE_ALT};
    }}

    QPushButton:disabled {{
        background: {BG_SURFACE};
        color: {TEXT_MUTED};
        border-color: {BORDER};
    }}

    QPushButton[variant="primary"] {{
        background: {ACCENT};
        color: white;
        border: none;
        font-weight: 600;
    }}

    QPushButton[variant="primary"]:hover {{
        background: {ACCENT_HOVER};
    }}

    QPushButton[variant="primary"]:pressed {{
        background: {ACCENT_PRESSED};
    }}

    QPushButton[variant="ghost"] {{
        background: transparent;
        border: 1px solid {BORDER};
        color: {TEXT_SECONDARY};
    }}

    QPushButton[variant="ghost"]:hover {{
        background: {BG_ELEVATED};
        color: {TEXT_PRIMARY};
    }}

    QPushButton[variant="danger"] {{
        background: transparent;
        border: 1px solid {ERROR};
        color: {ERROR};
    }}

    QPushButton[variant="danger"]:hover {{
        background: rgba(255, 92, 108, 0.12);
    }}

    QLineEdit, QComboBox, QSpinBox {{
        background: {BG_ELEVATED};
        border: 1px solid {BORDER_STRONG};
        border-radius: {RADIUS_SM}px;
        padding: 6px {SPACE_SM}px;
        color: {TEXT_PRIMARY};
        selection-background-color: {ACCENT};
    }}

    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
        border: 1px solid {ACCENT};
    }}

    QLineEdit:disabled {{
        color: {TEXT_MUTED};
    }}

    QComboBox::drop-down {{
        border: none;
        width: 24px;
    }}

    QSpinBox::up-button, QSpinBox::down-button {{
        width: 16px;
        border: none;
    }}

    QToolBar {{
        background: {BG_SURFACE};
        border: none;
        border-bottom: 1px solid {BORDER};
        padding: {SPACE_SM}px;
        spacing: {SPACE_XS}px;
    }}

    QToolButton {{
        background: transparent;
        color: {TEXT_SECONDARY};
        border: none;
        border-radius: {RADIUS_SM}px;
        padding: {SPACE_SM}px {SPACE_MD}px;
        font-weight: 500;
    }}

    QToolButton:hover {{
        background: {BG_ELEVATED};
        color: {TEXT_PRIMARY};
    }}

    QToolButton:pressed, QToolButton:checked {{
        background: {ACCENT_SOFT};
        color: {ACCENT_HOVER};
    }}

    QTableWidget {{
        background: {BG_SURFACE};
        alternate-background-color: {BG_SURFACE_ALT};
        gridline-color: {BORDER};
        border: 1px solid {BORDER};
        border-radius: {RADIUS}px;
        color: {TEXT_PRIMARY};
    }}

    QTableWidget::item {{
        padding: {SPACE_SM}px;
        border: none;
    }}

    QTableWidget::item:selected {{
        background: {ACCENT_SOFT_STRONG};
        color: {TEXT_PRIMARY};
    }}

    QHeaderView::section {{
        background: {BG_SURFACE_ALT};
        color: {TEXT_SECONDARY};
        padding: {SPACE_SM}px;
        border: none;
        border-bottom: 1px solid {BORDER};
        font-weight: 600;
    }}

    QTableCornerButton::section {{
        background: {BG_SURFACE_ALT};
        border: none;
    }}

    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 0;
    }}

    QScrollBar::handle:vertical {{
        background: {BORDER_STRONG};
        border-radius: 5px;
        min-height: 24px;
    }}

    QScrollBar::handle:vertical:hover {{
        background: {TEXT_MUTED};
    }}

    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}

    QScrollBar:horizontal {{
        background: transparent;
        height: 10px;
    }}

    QScrollBar::handle:horizontal {{
        background: {BORDER_STRONG};
        border-radius: 5px;
        min-width: 24px;
    }}

    QStatusBar {{
        background: {BG_SURFACE};
        color: {TEXT_SECONDARY};
        border-top: 1px solid {BORDER};
    }}

    QMessageBox {{
        background: {BG_SURFACE};
    }}
    """
