from __future__ import annotations

from enum import Enum


class PictureBrightness(str, Enum):
    """How bright the finished picture is. STANDARD is the genre's own look (for the moody genres a
    vignette, a brightness cut and heavy desaturation on top of dark footage); BRIGHTER leaves the
    vignette out and lifts the shadows, so a dark scene stays readable."""

    STANDARD = "standard"
    BRIGHTER = "brighter"
