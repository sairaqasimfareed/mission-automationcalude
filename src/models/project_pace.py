from __future__ import annotations

from enum import Enum


class ProjectPace(str, Enum):
    """How much room the video gives the viewer: the pause the picture stays after each spoken line and
    how fast the voice talks. NORMAL changes nothing (the genre's own pause, the voice's own speed).
    """

    RELAXED = "relaxed"
    NORMAL = "normal"
    FAST = "fast"

    @property
    def hold_offset_seconds(self) -> float:
        """Added to the genre's pause after each line (the operator's own pause choice is never changed)."""

        return {
            ProjectPace.RELAXED: 0.6,
            ProjectPace.NORMAL: 0.0,
            ProjectPace.FAST: -0.3,
        }[self]

    @property
    def voice_speed_factor(self) -> float:
        """Multiplies the voice's speed (ElevenLabs allows 0.7-1.2 in all)."""

        return {
            ProjectPace.RELAXED: 0.92,
            ProjectPace.NORMAL: 1.0,
            ProjectPace.FAST: 1.06,
        }[self]
