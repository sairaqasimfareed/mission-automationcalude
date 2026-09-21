from __future__ import annotations

from typing import Any

# Real-world finding, 2026-09-18: a real job's stored narration/
# research/reasoning text was found to contain corrupted em dashes
# ("cunning â€” but it wasn't." instead of "cunning
# — but it wasn't."), confirmed via direct reproduction NOT to be
# an LLM artifact - a controlled call through the exact same
# AnthropicProviderAdapter this app uses returned a clean, correctly
# UTF-8-encoded em dash. Every file read/write in this codebase was
# also checked and confirmed to use explicit UTF-8. The exact
# corruption signature (one legitimate UTF-8 multi-byte character
# turning into 2-3 separate characters, each one matching what that
# character's own UTF-8 bytes decode to under cp1252/Windows-1252) is
# the textbook "mojibake" pattern produced somewhere upstream
# mis-decoding genuinely correct UTF-8 bytes as cp1252 - Windows'
# default text encoding when none is specified, which several
# dependencies (not this codebase's own file I/O, already verified
# clean) can silently fall back to. Since the exact injection point
# could not be pinned down after exhausting the obvious candidates,
# this repairs the corruption at its one guaranteed chokepoint
# instead: every LLM response, real or corrupted, passes through
# LLMGateway.call() before reaching any pipeline stage.
_MOJIBAKE_MARKER = "â"  # U+00E2 (â) - present in every observed case


def repair_mojibake(text: str) -> str:
    """
    Detect and reverse UTF-8-decoded-as-cp1252 corruption in one string.

    Only attempts a repair when the telltale marker character is
    present, and only keeps the repaired version when the reversal
    (re-encoding as cp1252, then decoding those bytes as UTF-8 - the
    exact inverse of the corruption) succeeds AND removes the marker.
    Genuinely correct text containing a real "â" is either not valid
    cp1252-representable-then-invalid-as-UTF-8 (so the round trip
    raises and is left untouched) or, in the rare case it is, the
    repaired form would still contain no U+00E2 - either way this
    never touches text that was never actually corrupted.
    """

    if _MOJIBAKE_MARKER not in text:
        return text

    try:
        repaired = text.encode("cp1252").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return text

    if _MOJIBAKE_MARKER in repaired:
        return text

    return repaired


def repair_mojibake_deep(value: Any) -> Any:
    """
    Apply repair_mojibake to every string found anywhere inside a
    JSON-shaped value (dict/list/str, nested arbitrarily deep) -
    structured LLM responses (expect_json=True) carry narration/
    reasoning text as nested string values, not just as the top-level
    content string.
    """

    if isinstance(value, str):
        return repair_mojibake(value)

    if isinstance(value, dict):
        return {key: repair_mojibake_deep(item) for key, item in value.items()}

    if isinstance(value, list):
        return [repair_mojibake_deep(item) for item in value]

    return value
