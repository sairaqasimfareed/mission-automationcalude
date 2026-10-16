"""The `[VISUAL 8s] description` marker: a shot with a picture and no narration.

A script is plain text, written as paragraphs of narration (or `NAME: line` dialogue). A paragraph that
starts with this marker is not spoken: it describes what the viewer sees for a fixed time, with music and
sound effects still playing underneath.

    [VISUAL 8s] The camera drifts over the empty room.

The seconds are optional (`[VISUAL] ...` runs the default) and the unit may be written s, sec or seconds.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# One generated clip carries the whole scene, so a visual-only scene is limited to what one clip can be:
# Flow's longest clip is 8 s. A longer silent stretch is written as two markers.
MIN_VISUAL_SECONDS = 2.0
MAX_VISUAL_SECONDS = 8.0
DEFAULT_VISUAL_SECONDS = 6.0

_MARKER = re.compile(
    r"^\s*\[\s*(?:visual|silent)\s*:?\s*(?P<seconds>\d+(?:\.\d+)?)?\s*"
    r"(?:s|sec|secs|second|seconds)?\s*\]\s*:?\s*(?P<description>.*)$",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class VisualMarker:
    seconds: float
    description: str


def parse_visual_marker(paragraph: str) -> VisualMarker | None:
    """The marker's seconds and description, or None when the paragraph is ordinary text.

    A marker with no description, or seconds outside MIN..MAX, raises ValueError saying what to
    change - never guessed at, because the number decides how long the shot runs."""

    match = _MARKER.match(paragraph)

    if match is None:
        return None

    description = " ".join(match.group("description").split())

    if not description:
        raise ValueError(
            "A [VISUAL] marker needs a description of what is shown after it, "
            "for example: [VISUAL 8s] The camera drifts over the empty room."
        )

    raw_seconds = match.group("seconds")
    seconds = float(raw_seconds) if raw_seconds is not None else DEFAULT_VISUAL_SECONDS

    if not MIN_VISUAL_SECONDS <= seconds <= MAX_VISUAL_SECONDS:
        raise ValueError(
            f"A [VISUAL] scene can run {MIN_VISUAL_SECONDS:.0f} to {MAX_VISUAL_SECONDS:.0f} "
            f"seconds (one clip); '{description[:40]}' asks for {seconds:g}. "
            "Write two markers for a longer silent stretch."
        )

    return VisualMarker(seconds=seconds, description=description)
