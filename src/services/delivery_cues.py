"""Emotion tags in a script: `JUDGE: [stern] The court will hear the evidence.`

A tag is one or two lowercase words in square brackets. It is taken OUT of the script text when the
script is imported (the text everything else reads stays clean) and kept as a DeliveryCue that points
at the words it precedes. Only the voice step puts it back, and only for a voice model that understands
tags (ElevenLabs v3), so a tag can never be spoken aloud or shown in a subtitle. `[VISUAL 4s]` is not a
tag: it has capitals.
"""

from __future__ import annotations

import re

from src.models.delivery_cue import DeliveryCue

_TAG = re.compile(r"\[(?P<tag>[a-z][a-z' \-]{0,29})\]")
_ANCHOR_WORDS = 8
_QUOTES = '"“”'


def _clean_line(line: str) -> str:
    return re.sub(r"[ \t]{2,}", " ", _TAG.sub("", line)).strip()


def _anchor(text_after_tag: str) -> str:
    words = _clean_line(text_after_tag).split()[:_ANCHOR_WORDS]

    return " ".join(words).strip(_QUOTES).strip()


def extract_delivery_cues(raw_text: str) -> tuple[str, list[DeliveryCue]]:
    """`raw_text` without its emotion tags, and a cue for each tag that has words after it."""

    cues: list[DeliveryCue] = []
    lines: list[str] = []

    for line in raw_text.split("\n"):
        for match in _TAG.finditer(line):
            anchor = _anchor(line[match.end() :])

            if anchor:
                cues.append(DeliveryCue(anchor=anchor, tag=match.group("tag").strip()))

        lines.append(_clean_line(line) if _TAG.search(line) else line)

    return "\n".join(lines), cues


def apply_delivery_cues(cues: list[DeliveryCue], text: str) -> str | None:
    """`text` with each cue's tag put back in front of its words, or None when no cue belongs in it."""

    if not cues:
        return None

    flat = " ".join(text.split())
    inserts: list[tuple[int, str]] = []

    for cue in cues:
        position = flat.find(cue.anchor)

        if position >= 0:
            inserts.append((position, cue.tag))

    if not inserts:
        return None

    for position, tag in sorted(inserts, key=lambda item: item[0], reverse=True):
        flat = f"{flat[:position]}[{tag}] {flat[position:]}"

    return flat
