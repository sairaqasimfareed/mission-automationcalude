from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from src.desktop.theme import ACCENT, TEXT_PRIMARY, TEXT_SECONDARY

# Small hand-authored line-icon set (stroke-based, 24x24 viewbox) so the
# app never depends on downloading/bundling a third-party icon pack.
# Each entry is raw SVG body content (no outer <svg> tag) - _render()
# wraps it with a viewBox and the requested stroke color.

_ICONS: dict[str, str] = {
    "dashboard": (
        '<rect x="3" y="3" width="7" height="7" rx="1.5"/>'
        '<rect x="14" y="3" width="7" height="7" rx="1.5"/>'
        '<rect x="3" y="14" width="7" height="7" rx="1.5"/>'
        '<rect x="14" y="14" width="7" height="7" rx="1.5"/>'
    ),
    "add": (
        '<circle cx="12" cy="12" r="9"/>'
        '<line x1="12" y1="8" x2="12" y2="16"/>'
        '<line x1="8" y1="12" x2="16" y2="12"/>'
    ),
    "settings": (
        '<circle cx="12" cy="12" r="3"/>'
        '<path d="M19.4 13.5a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 '
        "1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1.03 1.55V19.5a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-1.03-1.55 "
        "1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.7 1.7 0 0 0 .34-1.87 1.7 1.7 "
        "0 0 0-1.55-1.03H4.5a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 6.14 8.6a1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 "
        "2 0 1 1 2.83-2.83l.06.06a1.7 1.7 0 0 0 1.87.34H10.6A1.7 1.7 0 0 0 11.63 2.6V2.5a2 2 0 1 1 4 0v.09a1.7 "
        "1.7 0 0 0 1.03 1.55c.66.28 1.42.14 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.7 1.7 0 0 0-.34 "
        '1.87V8.6c.28.66.85 1.15 1.55 1.03h.09a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.55 1.03z"/>'
    ),
    "back": (
        '<line x1="19" y1="12" x2="5" y2="12"/>' '<polyline points="12 19 5 12 12 5"/>'
    ),
    "research": (
        '<circle cx="10.5" cy="10.5" r="6.5"/>'
        '<line x1="20" y1="20" x2="15.3" y2="15.3"/>'
    ),
    "script": (
        '<path d="M6 3h9l4 4v14a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"/>'
        '<line x1="8" y1="12" x2="16" y2="12"/>'
        '<line x1="8" y1="16" x2="16" y2="16"/>'
        '<line x1="8" y1="8" x2="12" y2="8"/>'
    ),
    "shield": (
        '<path d="M12 3l7 3v6c0 4.5-3 8-7 9-4-1-7-4.5-7-9V6z"/>'
        '<polyline points="9 12 11 14 15.5 9.5"/>'
    ),
    "clapper": (
        '<path d="M3 9.5 20 6l1 4L4 13.5z"/>'
        '<rect x="3" y="10" width="18" height="10" rx="1.2"/>'
        '<line x1="7" y1="6.8" x2="9.3" y2="10.6"/>'
        '<line x1="12" y1="6" x2="14.3" y2="9.8"/>'
        '<line x1="17" y1="5.2" x2="19.3" y2="9"/>'
    ),
    "tag": (
        '<path d="M12 3h6a2 2 0 0 1 2 2v6l-9.5 9.5a2 2 0 0 1-2.8 0l-5.2-5.2a2 2 0 0 1 0-2.8z"/>'
        '<circle cx="15.5" cy="8.5" r="1.4"/>'
    ),
    "image": (
        '<rect x="3" y="3" width="18" height="18" rx="2"/>'
        '<circle cx="9" cy="9" r="2"/>'
        '<path d="M21 15l-5.5-5.5a1.5 1.5 0 0 0-2.1 0L3 20"/>'
    ),
    "play": ('<circle cx="12" cy="12" r="9"/>' '<polygon points="10 8 16 12 10 16"/>'),
    "package": (
        '<path d="M21 8 12 3 3 8v8l9 5 9-5z"/>'
        '<polyline points="3 8 12 13 21 8"/>'
        '<line x1="12" y1="13" x2="12" y2="21"/>'
    ),
    "upload": (
        '<path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>'
        '<polyline points="7 9 12 4 17 9"/>'
        '<line x1="12" y1="4" x2="12" y2="15"/>'
    ),
    "search": (
        '<circle cx="10.5" cy="10.5" r="6.5"/>'
        '<line x1="20" y1="20" x2="15.3" y2="15.3"/>'
    ),
    "check": ('<polyline points="4 12.5 9.5 18 20 6"/>'),
    "check-circle": (
        '<circle cx="12" cy="12" r="9"/>'
        '<polyline points="7.5 12.5 10.5 15.5 16.5 8.5"/>'
    ),
    "alert-triangle": (
        '<path d="M12 3.5 22 20H2z"/>'
        '<line x1="12" y1="9.5" x2="12" y2="14"/>'
        '<circle cx="12" cy="17" r="0.9" fill="{color}"/>'
    ),
    "x-circle": (
        '<circle cx="12" cy="12" r="9"/>'
        '<line x1="9" y1="9" x2="15" y2="15"/>'
        '<line x1="15" y1="9" x2="9" y2="15"/>'
    ),
    "folder": (
        '<path d="M3 6.5A1.5 1.5 0 0 1 4.5 5h5l2 2.5h8A1.5 1.5 0 0 1 21 9v9.5A1.5 1.5 0 0 1 '
        '19.5 20h-15A1.5 1.5 0 0 1 3 18.5z"/>'
    ),
    "export": (
        '<path d="M12 3v12"/>'
        '<polyline points="7.5 8.5 12 4 16.5 8.5"/>'
        '<path d="M5 15v4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4"/>'
    ),
}


def _wrap(body: str, *, color: str) -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        f"{body.format(color=color)}"
        "</svg>"
    )


@lru_cache(maxsize=256)
def _pixmap(name: str, color: str, size: int) -> QPixmap:
    body = _ICONS.get(name)

    if body is None:
        raise KeyError(f"Unknown icon: {name}")

    svg = _wrap(body, color=color)

    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))

    pixmap = QPixmap(QSize(size, size))
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()

    return pixmap


def icon(name: str, *, color: str = TEXT_SECONDARY, size: int = 18) -> QIcon:
    """Return a themed line icon, rendered from this app's own SVG set."""

    return QIcon(_pixmap(name, color, size))


def accent_icon(name: str, *, size: int = 18) -> QIcon:
    """Return a line icon rendered in the accent color."""

    return icon(name, color=ACCENT, size=size)


def primary_icon(name: str, *, size: int = 18) -> QIcon:
    """Return a line icon rendered in the primary text color."""

    return icon(name, color=TEXT_PRIMARY, size=size)


@lru_cache(maxsize=1)
def app_icon() -> QIcon:
    """
    Build the application window/taskbar icon.

    A rounded violet mark with a white play glyph - Mission Automation
    produces video, so a play-in-frame mark reads clearly even at
    small taskbar sizes without needing a bundled image asset.
    """

    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#8F72FF"/>'
        '<stop offset="1" stop-color="#6647E0"/>'
        "</linearGradient></defs>"
        '<rect x="2" y="2" width="60" height="60" rx="16" fill="url(#g)"/>'
        '<polygon points="25,19 47,32 25,45" fill="#F3F4F7"/>'
        "</svg>"
    )

    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))

    result = QIcon()

    for size in (16, 24, 32, 48, 64, 128, 256):
        pixmap = QPixmap(QSize(size, size))
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()

        result.addPixmap(pixmap)

    return result
