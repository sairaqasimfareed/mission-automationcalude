"""Reads a voice-cast script: one line per beat, some of them spoken by named voices.

    JUDGE: The court will hear the evidence.
    The charges: men's dress, refusing the Church.
    [VISUAL 4s] A candle flame shivers; dust drifts across the type.
    VOICE (Joan of Arc): All I said and revoked, I said for fear of the fire.

Every non-blank line is its own beat (blank lines are optional). A line is spoken by a named voice only when it
starts with an ALL-CAPS name and a colon (`JUDGE:`, `JOAN OF ARC:`) or `VOICE (Name):`. Anything else, including
a line that merely contains a colon ("Charge: heresy. May 24th, 1431: life in prison."), is read by the
narrator. A line that starts with `[VISUAL 4s]` is a shot with no speech (see visual_scene_marker).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.models.dialogue import MAX_SPEAKER_NAME_CHARACTERS, NARRATOR_NAME
from src.services.visual_scene_marker import VisualMarker, parse_visual_marker

# An ALL-CAPS name of up to four words: no lowercase letters, so "Charge:" or "The charges:" is not a speaker.
_CAPS_TAG = re.compile(
    r"^(?P<name>[A-Z][A-Z0-9.'’\-]*(?: [A-Z0-9.'’\-]+){0,3})\s*:\s*(?P<text>\S.*)$"
)
_VOICE_TAG = re.compile(
    rf"^VOICE\s*\(\s*(?P<name>[^)]{{1,{MAX_SPEAKER_NAME_CHARACTERS}}})\s*\)\s*:\s*(?P<text>\S.*)$",
    re.IGNORECASE,
)
_QUOTES = '"“”'


@dataclass(frozen=True)
class CastLine:
    """One spoken beat. `speaker` is None for a line the narrator reads."""

    speaker: str | None
    text: str


CastItem = CastLine | VisualMarker


def canonical_speaker(raw: str) -> str:
    """ "JOAN OF ARC" -> "Joan Of Arc"; a name written with its own capitals ("Joan of Arc", from a
    VOICE (...) tag) is kept as written. NARRATOR means no named voice."""

    name = " ".join(raw.split())

    return name.title() if name.isupper() else name


def _strip_quotes(text: str) -> str:
    return text.strip().strip(_QUOTES).strip()


def parse_cast_line(line: str) -> CastItem | None:
    """The beat one line holds, or None for a blank line."""

    stripped = line.strip()

    if not stripped:
        return None

    visual = parse_visual_marker(stripped)

    if visual is not None:
        return visual

    match = _VOICE_TAG.match(stripped) or _CAPS_TAG.match(stripped)

    if match is None:
        return CastLine(speaker=None, text=stripped)

    name = canonical_speaker(match.group("name"))
    text = _strip_quotes(match.group("text"))

    if not text:
        return CastLine(speaker=None, text=stripped)

    if name.lower() == NARRATOR_NAME.lower():
        return CastLine(speaker=None, text=text)

    return CastLine(speaker=name, text=text)


def parse_cast_script(raw_text: str) -> list[CastItem]:
    """Every beat of the script in order. Raises ValueError when it holds none."""

    items = [
        item
        for item in (
            parse_cast_line(line)
            for line in raw_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        )
        if item is not None
    ]

    if not items:
        raise ValueError("Imported script text is empty.")

    return items


def speakers_of_cast(items: list[CastItem]) -> list[str]:
    """The named voices in the script, once each, in order of first appearance (the narrator excluded)."""

    seen: list[str] = []

    for item in items:
        if isinstance(item, CastLine) and item.speaker and item.speaker not in seen:
            seen.append(item.speaker)

    return seen
