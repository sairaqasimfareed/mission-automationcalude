"""Subtitle size and position for a vertical (9:16) picture.

The caption styles were designed for a landscape 1080p frame: 48-60 px text sitting 60-90 px
above the bottom edge. Put on a 1080x1920 vertical video that is the very bottom of the
picture, where TikTok, Reels and Shorts draw their own caption, account name and buttons -
so the subtitles would sit under them (the apps' bottom 15-25% is covered; 26% is kept clear
here to stay well outside it). The text is also small for a phone held upright. So for a
vertical frame the text is made larger and lifted into the lower-middle of the picture.
A landscape frame is left exactly as the style defines it.
"""

from __future__ import annotations

# The short side of the frame the styles were designed for (a 1920x1080 landscape frame).
_REFERENCE_SHORT_SIDE = 1080
# Phones are held upright and viewed small: vertical text is made this much larger than
# the style's own size at the same frame width.
PORTRAIT_FONT_BOOST = 1.3
# The text's bottom edge sits this share of the frame's height above the bottom.
PORTRAIT_BOTTOM_CLEARANCE = 0.26


def is_portrait(width: int | None, height: int | None) -> bool:
    return bool(width and height and height > width)


def adapt_style_for_frame(
    style: dict[str, str], *, width: int | None, height: int | None
) -> dict[str, str]:
    """The style to draw with: unchanged for landscape (or an unknown size); for a
    vertical frame a larger font and outline (scaled to the frame's width) and a position
    that keeps the text clear of the platforms' bottom overlays."""

    if not is_portrait(width, height):
        return dict(style)

    assert width is not None

    scale = (width / _REFERENCE_SHORT_SIDE) * PORTRAIT_FONT_BOOST
    adapted = dict(style)

    try:
        adapted["fontsize"] = str(max(12, round(int(style["fontsize"]) * scale)))
    except (KeyError, ValueError):
        pass

    try:
        adapted["borderw"] = str(max(1, round(int(style["borderw"]) * scale)))
    except (KeyError, ValueError):
        pass

    adapted["y"] = f"h-text_h-h*{PORTRAIT_BOTTOM_CLEARANCE}"

    return adapted
