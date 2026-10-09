"""Wording a generated clip cannot use.

Each clip is generated on its own, from its prompt alone. "Same rural village" or "as before"
means nothing to a generator that has never seen the village (live, 2026-10-08: Lake Nyos prompts
read "Environment: Same rural village. Lighting: Natural daylight."), and "unspecified" says
nothing at all. These helpers find that wording; the prompt compiler removes it where it can, and
`PromptCompletenessService` reports what is left.
"""

from __future__ import annotations

import re

# "same", "similar to", "as before", "as in the previous shot", "previous scene" ... as words.
RELATIVE_WORDING = re.compile(
    r"\b(?:the\s+same|same|similar\s+to|as\s+before|as\s+in\s+the\s+previous|"
    r"previous\s+(?:scene|shot|clip)|as\s+earlier|unchanged)\b",
    re.IGNORECASE,
)

_LEADING_RELATIVE = re.compile(
    r"^\s*(?:the\s+)?(?:same|similar\s+to|unchanged)\b[\s,:;-]*(?:as\s+(?:before|earlier)\b[\s,:;-]*)?",
    re.IGNORECASE,
)

_UNSPECIFIED = frozenset({"", "unspecified", "unknown", "n/a", "none", "tbd"})


def is_unspecified(value: str | None) -> bool:
    return (value or "").strip().strip(".").lower() in _UNSPECIFIED


def relative_words_in(text: str) -> list[str]:
    """The relative wording found in `text`, lower-cased, in order, without repeats."""

    found: list[str] = []

    for match in RELATIVE_WORDING.finditer(text):
        word = " ".join(match.group(0).lower().split())

        if word not in found:
            found.append(word)

    return found


def without_leading_relative_wording(text: str) -> str:
    """ "Same rural village" -> "Rural village" (capitalised again); text with no leading
    relative wording is returned unchanged."""

    cleaned = _LEADING_RELATIVE.sub("", text, count=1).strip()

    if cleaned == text.strip():
        return text

    return cleaned[:1].upper() + cleaned[1:] if cleaned else ""
