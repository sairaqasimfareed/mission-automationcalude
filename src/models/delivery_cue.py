from __future__ import annotations

from src.models.base import MissionBaseModel


class DeliveryCue(MissionBaseModel):
    """One emotion word written into the operator's script, e.g. `[stern]` before "The court will
    hear the evidence." The script itself is stored WITHOUT the tag (so subtitles, prompts and word
    counts never see it); the cue remembers which words it goes in front of - `anchor` is the first
    words after the tag - and the voice step puts it back only when it asks the voice model.
    """

    anchor: str
    tag: str
