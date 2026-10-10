"""How much a scene's characters have to say against how long its clip is.

On camera a person speaks at most about 2.5 words a second. A scene whose lines hold more words than
the clip can carry makes the video provider rush the speech (live, 2026-10-08: two lines written for
about 9.6 s of speech were squeezed into 8 s and both voices ran at roughly 3.5-3.9 words a second).
This only measures and reports; it never rewrites a line or splits a scene.

The clip a scene can have is its planned length (sized from its words) capped by the provider's longest
clip: 10 s on Muse, 8 s on Flow.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from src.models.scene import Scene

MAX_WORDS_PER_SECOND = 2.5


@dataclass(frozen=True)
class SpeechBudget:
    words: int
    clip_seconds: float
    allowed_words: int

    @property
    def over(self) -> bool:
        return self.words > self.allowed_words

    @property
    def words_per_second(self) -> float:
        return self.words / self.clip_seconds if self.clip_seconds > 0 else float("inf")


def speech_budget(scene: Scene, *, max_clip_seconds: float) -> SpeechBudget | None:
    """The budget for a scene with dialogue, or None for a narrated scene."""

    if not scene.dialogue:
        return None

    clip_seconds = min(float(scene.estimated_duration_seconds), max_clip_seconds)

    return SpeechBudget(
        words=sum(line.word_count for line in scene.dialogue),
        clip_seconds=clip_seconds,
        allowed_words=math.floor(MAX_WORDS_PER_SECOND * clip_seconds),
    )


def speech_budget_message(budget: SpeechBudget) -> str:
    return (
        f"{budget.words} words of dialogue for a {budget.clip_seconds:.0f} s clip "
        f"({budget.words_per_second:.1f} words a second; people speak about "
        f"{MAX_WORDS_PER_SECOND} at most, so the clip fits about {budget.allowed_words}). "
        "The speech will be rushed - shorten the lines or split the exchange into two scenes."
    )
