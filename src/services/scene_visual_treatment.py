from __future__ import annotations

import re

from src.models.scene import Scene
from src.models.shot_planning import ShotSpecification
from src.models.visual_continuity import (
    CanonicalEntityIdentity,
    CanonicalEntityType,
    ClipContinuityEntry,
    VisualContinuityBible,
)

# Words that mark a scene the plan wants drawn as a graphic - an infographic, a
# diagram, a text overlay - instead of filmed. The plan is free text written by
# Claude, so this is a keyword check on its own words, deliberately generous: a
# wrong "graphic" label costs a visible hint the operator can ignore, a missed
# one costs an invented infographic.
_GRAPHIC_PATTERN = re.compile(
    r"infographic|graphic|overlay|diagram|\bchart\b|title card|text card|"
    r"on-screen text|data visuali[sz]ation|\bicons?\b",
    re.IGNORECASE,
)

_EXACT_TEXT_LIMIT = 160


def is_graphic_scene(
    *, entry: ClipContinuityEntry | None, shot: ShotSpecification | None
) -> bool:
    """Whether the plan describes this scene as a graphic rather than a filmed
    shot - judged from the plan's own wording for its setting, composition and
    action. It does not look at the live-footage switch (see `renders_as_graphic`)."""

    parts: list[str] = []

    if entry is not None:
        parts.extend([entry.outgoing_state.location, entry.incoming_state.location])

    if shot is not None:
        parts.extend([shot.composition, shot.action, shot.lighting])

    return any(_GRAPHIC_PATTERN.search(part or "") for part in parts)


def renders_as_graphic(
    *,
    scene: Scene,
    entry: ClipContinuityEntry | None,
    shot: ShotSpecification | None,
) -> bool:
    """A graphic scene the operator has not switched to live footage."""

    return not scene.treat_as_live_footage and is_graphic_scene(entry=entry, shot=shot)


def exact_text_for(scene: Scene) -> str:
    """The words a graphic scene may show on screen: its own narration, cut at a
    word boundary if it is long. Using the script's own words keeps a generator
    from inventing a second sentence (live, 2026-10-07: scene 13's infographic added
    a line about bedtime that the narration never said)."""

    text = " ".join(scene.narration.split())

    if len(text) <= _EXACT_TEXT_LIMIT:
        return text

    cut = text[:_EXACT_TEXT_LIMIT].rsplit(" ", 1)[0]

    return cut.rstrip(",;:") + "..."


def main_place(bible: VisualContinuityBible) -> CanonicalEntityIdentity | None:
    """The project's main recurring place - the setting a graphic scene is shown
    in when switched to live footage. Prefers one that already has a reference
    picture, then the first listed."""

    places = [
        identity
        for identity in bible.identities
        if identity.entity_type == CanonicalEntityType.LOCATION
    ]

    for place in places:
        if place.reference_asset_ids:
            return place

    return places[0] if places else None


def effective_on_screen_names(bible: VisualContinuityBible, scene: Scene) -> list[str]:
    """Who and what is on screen in this scene, for deciding which references to
    take and attach. The bible's own list, plus - for a graphic scene switched to
    live footage - the project's main place, which is what that footage shows."""

    entry = bible.entry_for_scene(scene.scene_number)
    names = list(entry.on_screen_entity_names) if entry is not None else []

    if scene.treat_as_live_footage:
        place = main_place(bible)

        if place is not None and place.name not in names:
            names.append(place.name)

    return names
