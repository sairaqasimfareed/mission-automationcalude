"""A small colour correction applied to one clip so it sits with the others.

Generated clips of one video come back with their own exposure and colour (live,
2026-10-07: a bright daylight clip between dark kitchen ones). The correction is mild and
bounded on purpose - it nudges a clip toward the video's typical look, it does not
re-grade it.
"""

from __future__ import annotations

from pydantic import Field

from src.models.base import MissionBaseModel

# The most any one clip is ever moved.
MAX_BRIGHTNESS_SHIFT = 0.12
MIN_SATURATION = 0.8
MAX_SATURATION = 1.25
MAX_CHANNEL_GAIN_SHIFT = 0.08


class ColorCorrection(MissionBaseModel):
    # Added to the clip's brightness (FFmpeg `eq` brightness, -1..1 scale).
    brightness: float = Field(
        default=0.0, ge=-MAX_BRIGHTNESS_SHIFT, le=MAX_BRIGHTNESS_SHIFT
    )
    # Multiplies the clip's saturation.
    saturation: float = Field(default=1.0, ge=MIN_SATURATION, le=MAX_SATURATION)
    # Multiply the red and blue channels: warmer = more red, less blue.
    red_gain: float = Field(
        default=1.0, ge=1 - MAX_CHANNEL_GAIN_SHIFT, le=1 + MAX_CHANNEL_GAIN_SHIFT
    )
    blue_gain: float = Field(
        default=1.0, ge=1 - MAX_CHANNEL_GAIN_SHIFT, le=1 + MAX_CHANNEL_GAIN_SHIFT
    )

    @property
    def is_identity(self) -> bool:
        """True when applying it would change nothing visible."""

        return (
            abs(self.brightness) < 0.005
            and abs(self.saturation - 1.0) < 0.01
            and abs(self.red_gain - 1.0) < 0.005
            and abs(self.blue_gain - 1.0) < 0.005
        )
