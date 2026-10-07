"""Break a subtitle line in two (or three) when it is too wide for a narrow picture.

A subtitle is one drawn line of up to 8 words. In a 1920-wide landscape picture that fits;
in a 1080-wide vertical one it runs edge to edge (measured, 2026-10-07: one 47-character
line spanned x=22 to x=1056 of 1080) and a longer one is cut off at the sides - and the
outer margins of a vertical video are covered by the platform's own buttons anyway. The
line is broken into balanced rows instead, which the drawn text keeps centred.
"""

from __future__ import annotations

import math
import textwrap

# How wide one character is, as a share of the font size, for the fonts subtitles use
# (measured on Arial: about 0.46; a little more is assumed so a wide line still fits).
_CHARACTER_WIDTH_RATIO = 0.5
# Text may fill this much of the picture's width; the rest is margin.
_USABLE_WIDTH_FRACTION = 0.84


def max_characters_per_line(*, frame_width: int, fontsize: int) -> int:
    """How many characters of a subtitle fit on one row of a picture this wide."""

    if frame_width <= 0 or fontsize <= 0:
        return 10_000

    return max(
        8,
        int(frame_width * _USABLE_WIDTH_FRACTION / (fontsize * _CHARACTER_WIDTH_RATIO)),
    )


def wrap_for_frame(text: str, *, frame_width: int | None, fontsize: int) -> str:
    """`text` with line breaks added so no row is wider than the picture allows. A line
    that already fits, or an unknown picture width, is returned unchanged. Rows are
    balanced (two rows of similar length, not one long row and a stub)."""

    if not frame_width:
        return text

    maximum = max_characters_per_line(frame_width=frame_width, fontsize=fontsize)
    flat = " ".join(text.split())

    if len(flat) <= maximum:
        return text

    rows = math.ceil(len(flat) / maximum)
    width = min(maximum, math.ceil(len(flat) / rows) + 3)
    wrapped = textwrap.wrap(
        flat, width=width, break_long_words=False, break_on_hyphens=False
    )

    return "\n".join(wrapped)
