"""The one style line added in front of every clip prompt, in every project.

A video generator makes photorealistic footage unless it is told otherwise in words, and the
project look only has boxes for lighting, colour and camera. One line, entered once in Settings
("Hand-drawn 2D animation, heavy black ink outlines, flat cel colour, never photorealistic"),
is added as the first words of every compiled prompt - no per-project work, no drafting.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

DEFAULT_STYLE_LINE_PATH = Path("data/style_line.json")
MAX_STYLE_LINE_CHARACTERS = 300


def clean_style_line(text: str) -> str:
    """The line on one row of single spaces, cut at a word boundary to the limit."""

    collapsed = " ".join(text.split())

    if len(collapsed) <= MAX_STYLE_LINE_CHARACTERS:
        return collapsed

    return collapsed[:MAX_STYLE_LINE_CHARACTERS].rsplit(" ", 1)[0].rstrip(" ,;")


class StyleLineStore:
    """Persists the style line in its own small JSON file (like the other data/*.json state)."""

    def __init__(self, *, path: Path | None = None) -> None:
        self._path = path if path is not None else DEFAULT_STYLE_LINE_PATH

    def load(self) -> str:
        """The saved line, or "" when none was saved or the file is missing or unreadable -
        a bad file must never stop a prompt from being built."""

        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            value = data["style_line"]
        except (OSError, ValueError, KeyError, TypeError):
            return ""

        return clean_style_line(value) if isinstance(value, str) else ""

    def save(self, text: str) -> str:
        """Save the cleaned line (an empty one removes the style line); returns what was kept."""

        cleaned = clean_style_line(text)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps({"style_line": cleaned}, indent=2), encoding="utf-8"
        )

        return cleaned


# Where the compiler reads the line from. Nothing is set by default (tests, the command line):
# the desktop app points it at its store when it starts.
_style_line_source: Callable[[], str] = lambda: ""  # noqa: E731


def set_style_line_source(source: Callable[[], str]) -> None:
    global _style_line_source
    _style_line_source = source


def current_style_line() -> str:
    try:
        return clean_style_line(_style_line_source())
    except (
        Exception
    ):  # noqa: BLE001 - a style line must never stop a prompt from being built
        return ""


def with_style_line(look: str) -> str:
    """`look` with the style line in front of it. A look that already contains the line (typed
    into a project's own boxes) is not given it twice."""

    line = current_style_line()

    if not line or line.lower().rstrip(".") in look.lower():
        return look

    return f"{line.rstrip('.')}. {look}".rstrip()
