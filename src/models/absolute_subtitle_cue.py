from __future__ import annotations

from pydantic import Field, model_validator

from src.models.base import MissionBaseModel


class AbsoluteSubtitleCue(MissionBaseModel):
    """
    REQ-0 (post-render subtitle burn-in): one subtitle line, positioned
    in ABSOLUTE seconds against an already-finished, fully-composited
    video's own single continuous timeline - not a per-scene-relative
    offset (see SubtitleExecution's own local_start_offset_seconds,
    which this model deliberately does not reuse: that field means
    something only inside a per-scene filter chain, which no longer
    exists once a scene has already been crossfaded into one
    continuous video stream).
    """

    text: str
    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(gt=0.0)

    @model_validator(mode="after")
    def validate_range(self) -> AbsoluteSubtitleCue:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("A subtitle cue must end after it starts.")

        return self
