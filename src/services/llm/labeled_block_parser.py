from __future__ import annotations

import re


def extract_labeled_field(text: str, label: str) -> str | None:
    """
    Extract one "LABEL: value" line's value from an LLM response.

    Shared by services that ask an LLM for labeled plain-text blocks
    instead of JSON - see ThumbnailConceptGenerationService's
    docstring for why this codebase prefers that shape over
    expect_json/response_schema (the dry-run adapter's generic filler
    text has no JSON structure, and real providers follow an explicit
    label more reliably than a JSON schema for short structured
    extraction).
    """

    # [ \t]* (not \s*) after the colon deliberately does not match a
    # newline - \s* there would let an empty value on one line
    # silently capture the following line's content instead of
    # correctly finding no value.
    pattern = re.compile(
        rf"^\s*{re.escape(label)}\s*:[ \t]*(.+)$",
        re.IGNORECASE | re.MULTILINE,
    )

    match = pattern.search(text)

    if match is None:
        return None

    value = match.group(1).strip()

    return value or None
