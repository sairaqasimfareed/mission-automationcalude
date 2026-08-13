from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

# Dark, cinematic palette - a video-production tool spends most of its
# life next to a real editor/preview, so a bright default theme would
# fight the footage instead of getting out of its way.

BG_WINDOW = "#12141A"
BG_SURFACE = "#1B1E27"
BG_SURFACE_ALT = "#20232E"
BG_ELEVATED = "#262A36"

BORDER = "#2E3340"
BORDER_STRONG = "#3A4050"

TEXT_PRIMARY = "#F3F4F7"
TEXT_SECONDARY = "#A6ACBA"
TEXT_MUTED = "#6B7280"

ACCENT = "#7C5CFC"
ACCENT_HOVER = "#8F72FF"
ACCENT_PRESSED = "#6647E0"
ACCENT_SOFT = "rgba(124, 92, 252, 0.18)"
ACCENT_SOFT_STRONG = "rgba(124, 92, 252, 0.32)"

SUCCESS = "#3DD68C"
WARNING = "#F5A623"
ERROR = "#FF5C6C"
INFO = "#4EA1F3"

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


def apply_theme(app: QApplication) -> None:
    """Apply the shared font and stylesheet to the whole application."""

    font = QFont(FONT_FAMILY, SIZE_BODY)
    app.setFont(font)
    app.setStyleSheet(_build_stylesheet())


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
