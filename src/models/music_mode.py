"""How a project's background music is made."""

from __future__ import annotations

from enum import Enum


class MusicMode(str, Enum):
    # One piece per planned mood, joined with short fades (the original behaviour).
    PIECES = "pieces"
    # One composed track for the whole video, shaped by the planned moods, so the music
    # flows instead of being several separate pieces stitched together.
    CONTINUOUS = "continuous"
