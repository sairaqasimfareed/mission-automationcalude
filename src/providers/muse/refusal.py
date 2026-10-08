"""Recognising that Muse answered a prompt with a refusal instead of a video.

Muse is a chat: when its video tool refuses a request (live, 2026-10-08: "The tool refused that
specific combination - the prompt plus that image together. It judges each request on its own and
doesn't give me a detailed reason, and I can't override it. The text-only version of the same shot is
still available if you want it.") it replies with text and no video. The adapter used to keep waiting
for a video until the poll limit and then fail vaguely. Recognising the refusal lets the run move on:
retry once without the reference picture, and otherwise report Muse's own words.
"""

from __future__ import annotations

import re

# Wording a refusal uses. Deliberately specific - a status line such as "Generating your video" or a
# short caption must not match.
_REFUSAL_PATTERNS = (
    re.compile(r"\brefus(?:e|es|ed|al|ing)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:can(?:'|’)?t|cannot|can not|unable to|not able to|won(?:'|’)?t be able to)"
        r"\s+(?:generate|create|make|produce|render|do)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:didn(?:'|’)?t|did not|wasn(?:'|’)?t|was not)\s+"
        r"(?:go through|generate|work|accepted)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bdeclin(?:e|ed|es)\b", re.IGNORECASE),
    re.compile(r"\b(?:content|safety|usage)\s+polic(?:y|ies)\b", re.IGNORECASE),
)

# Longest stretch of Muse's reply kept in the failure message.
_MAX_REPLY_CHARACTERS = 500

# Reads the text of every chat message AFTER the one holding this attempt's own prompt (matched on
# the prompt's tail, as _follows_submitted_prompt does). null = the prompt message was not found.
REPLY_TEXT_AFTER_PROMPT_SCRIPT = """(anchor) => {
    const items = Array.from(document.querySelectorAll('[data-message-item]'));
    const norm = (text) => (text || '').replace(/\\s+/g, ' ').trim();
    let last = -1;
    items.forEach((item, index) => {
        if (norm(item.textContent).includes(anchor)) last = index;
    });
    if (last < 0) return null;
    return items.slice(last + 1).map((item) => norm(item.textContent))
        .filter((text) => text.length > 0).join(' | ');
}"""


def looks_like_refusal(reply_text: str | None) -> bool:
    """True when Muse's reply reads as a refusal (it said it would not or could not make the
    video)."""

    if not reply_text or not reply_text.strip():
        return False

    return any(pattern.search(reply_text) for pattern in _REFUSAL_PATTERNS)


def refusal_message(reply_text: str) -> str:
    """The failure message: Muse's own words, shortened."""

    cleaned = " ".join(reply_text.split())

    if len(cleaned) > _MAX_REPLY_CHARACTERS:
        cleaned = cleaned[:_MAX_REPLY_CHARACTERS].rstrip() + "..."

    return f"Muse refused this request: {cleaned}"
