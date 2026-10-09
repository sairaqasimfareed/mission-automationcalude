"""Reads the operator's own `NAME: line` script (Character-Oriented Video mode).

Blank lines separate scenes; each non-blank line inside one is a spoken line, written as a
speaker's name, a colon and what is said:

    WALTER: Postmaster says the afternoon train is late again.

    WALTER: We cannot hold the post past six.
    FRANK: Then you had better start sorting.

Deliberately strict. A line with no speaker is an error that names its line number, not a
continuation of the line above: a missing colon would otherwise silently put one character's
words in another's mouth, and the clip is lip-synced to whoever the prompt says is speaking.
"""

from __future__ import annotations

import re

from src.models.dialogue import (
    MAX_SPEAKER_NAME_CHARACTERS,
    DialogueLine,
    speakers_in,
)

# A speaker name: letters, digits and the punctuation names use. It must not hold sentence
# punctuation, so "Note that it rained: he left" is not read as a speaker called "Note that it
# rained".
_LINE = re.compile(
    r"^\s*(?P<speaker>[^\s:,;!?\"“”()\[\]][^:,;!?\"“”()\[\]]*?)\s*:\s*(?P<text>\S.*?)\s*$"
)
# A name is a few words; anything longer before a colon is a sentence, not a speaker.
_MAX_NAME_WORDS = 5
_QUOTES = '"“”'


class DialogueScriptError(ValueError):
    """The script is not a valid `NAME: line` script; the message says which line and why."""


def _canonical_name(raw: str) -> str:
    name = " ".join(raw.split())

    # "WALTER HALE" and "Walter Hale" are the same person; ALL CAPS is a script convention,
    # not part of the name.
    return name.title() if name.isupper() and len(name) > 1 else name


def _strip_quotes(text: str) -> str:
    stripped = text.strip()

    if len(stripped) >= 2 and stripped[0] in _QUOTES and stripped[-1] in _QUOTES:
        stripped = stripped[1:-1].strip()

    return stripped


def parse_dialogue_script(raw_text: str) -> list[list[DialogueLine]]:
    """One list of lines per scene (per blank-line-separated block), in order.

    Raises DialogueScriptError for an empty script, a line with no speaker, a speaker name
    that is too long, or a line with no words."""

    lines = raw_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    scenes: list[list[DialogueLine]] = []
    current: list[DialogueLine] = []
    names: dict[str, str] = {}

    for number, raw in enumerate(lines, start=1):
        if not raw.strip():
            if current:
                scenes.append(current)
                current = []

            continue

        match = _LINE.match(raw)

        if match is not None and len(match.group("speaker").split()) > _MAX_NAME_WORDS:
            match = None

        if match is None:
            raise DialogueScriptError(
                f"Line {number} has no speaker: write it as NAME: what they say "
                f"(got: {raw.strip()[:60]!r})."
            )

        name = _canonical_name(match.group("speaker"))

        if len(name) > MAX_SPEAKER_NAME_CHARACTERS:
            raise DialogueScriptError(
                f"Line {number}: the speaker name is longer than "
                f"{MAX_SPEAKER_NAME_CHARACTERS} characters."
            )

        # The first spelling of a name is the one kept, whatever the case on later lines.
        name = names.setdefault(name.lower(), name)
        text = _strip_quotes(match.group("text"))

        if not text:
            raise DialogueScriptError(f"Line {number} has a speaker but no words.")

        current.append(DialogueLine(speaker=name, text=text))

    if current:
        scenes.append(current)

    if not scenes:
        raise DialogueScriptError(
            "The script is empty: write lines as NAME: what they say."
        )

    return scenes


def speakers_of(scenes: list[list[DialogueLine]]) -> list[str]:
    """Every speaker in the script, once, in order of first appearance."""

    return speakers_in([line for scene in scenes for line in scene])
