"""Which person in the continuity bible is a given speaker.

Kept as a small module of its own (nothing heavy imported) because both the speaker-linking service
and the prompt compiler need it.
"""

from __future__ import annotations

from src.models.visual_continuity import (
    CanonicalEntityIdentity,
    CanonicalEntityType,
    VisualContinuityBible,
)


def find_person(
    bible: VisualContinuityBible | None, speaker: str
) -> CanonicalEntityIdentity | None:
    """The person in the bible this speaker is: the same name, or the same first name where
    one name continues the other ("Walter" and "Walter Hale"). More than one candidate is no
    match - guessing would put a line in the wrong character's mouth. A place with the
    speaker's name is never the speaker."""

    if bible is None:
        return None

    people = [
        identity
        for identity in bible.identities
        if identity.entity_type == CanonicalEntityType.PERSON
    ]
    wanted = speaker.lower().split()

    exact = [i for i in people if i.name.lower().split() == wanted]

    if exact:
        return exact[0]

    partial = [
        i
        for i in people
        if (theirs := i.name.lower().split())
        and (theirs[: len(wanted)] == wanted or wanted[: len(theirs)] == theirs)
    ]

    return partial[0] if len(partial) == 1 else None
