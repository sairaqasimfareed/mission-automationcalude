"""Small, rule-based edits that make the video-wide parts of a prompt fit ONE scene's shot.

The project's look line (palette, camera feel) is written once and repeated in every scene's
prompt, so it says things that are true of the video but wrong or unhelpful for a given shot - a
rule about mouths in a shot of a hand, "slow push-ins" under a locked-off camera. Each helper
here changes only the look sentence or a description for the scene it is compiled for; nothing
stored is changed, and no genre is named: they read what the shot actually shows.
"""

from __future__ import annotations

import re

# "... and no mouth is ever shown moving", "faces stay in shadow", "lips never move".
_FACE_WORDS = re.compile(
    r"\b(?:mouths?|lips?|lip[- ]?sync(?:ed|ing)?|speaking|talking)\b", re.IGNORECASE
)
_CLAUSE_SPLIT = re.compile(r"(,\s+(?:and\s+|but\s+)?|;\s+)")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def look_without_face_rules(look: str, *, person_on_screen: bool) -> str:
    """The look sentence without its rules about mouths and speech when no person is on
    screen in this scene.

    The rule exists for shots that show people (no moving mouths in a drawn style), and in a
    shot of a hand, a candle or a seal it only invites the generator to add a face. Only the
    clause that names the mouth is dropped: "Lines stay heavy and black, and no mouth is ever
    shown moving." keeps its first half."""

    if person_on_screen or not look or not _FACE_WORDS.search(look):
        return look

    kept_sentences: list[str] = []

    for sentence in _SENTENCE_SPLIT.split(look):
        if not _FACE_WORDS.search(sentence):
            kept_sentences.append(sentence)

            continue

        ending = sentence[-1] if sentence[-1] in ".!?" else ""
        body = sentence[: -len(ending)] if ending else sentence
        pieces = _CLAUSE_SPLIT.split(body)
        clauses, separators = pieces[0::2], pieces[1::2]
        rebuilt = ""

        for index, clause in enumerate(clauses):
            if _FACE_WORDS.search(clause):
                continue

            rebuilt = (
                clause if not rebuilt else rebuilt + separators[index - 1] + clause
            )

        if rebuilt:
            kept_sentences.append(rebuilt + ending)

    return " ".join(kept_sentences)
