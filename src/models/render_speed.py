from __future__ import annotations

from enum import Enum


class RenderSpeed(str, Enum):
    """How much time a render may take, traded against the last bit of finish.

    FINAL keeps the whole look (film grain included) at the encoder's best quality - the setting every project
    has always rendered with. BALANCED and DRAFT leave the film grain out, which on the app's own measurements is
    by far the most expensive single filter (about 6 times the cost of encoding the picture), and encode faster.
    The cuts, transitions, colour, vignette, zoom, subtitles and audio are identical in every mode.
    """

    FINAL = "final"
    BALANCED = "balanced"
    DRAFT = "draft"

    @property
    def x264_preset(self) -> str:
        return {
            RenderSpeed.FINAL: "medium",
            RenderSpeed.BALANCED: "fast",
            RenderSpeed.DRAFT: "veryfast",
        }[self]

    @property
    def film_grain(self) -> bool:
        return self == RenderSpeed.FINAL
