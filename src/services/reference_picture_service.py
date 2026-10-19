"""Reference pictures under the operator's control (the References tab).

Two modes (see ReferenceMode). AUTO is the long-standing behaviour: the app takes the best frame from a
clip it generated and attaches it to later scenes. MANUAL attaches only pictures the operator supplied: one
uploaded for a character or place, or one chosen for a single scene. This module holds what MANUAL needs:
which pictures count, which scenes a character or place is marked in, which ones still have no picture, and
the text the operator can paste into an image generator to make one in the series' style.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.models.asset_index import IndexedAsset
from src.models.reference_mode import ReferenceMode
from src.models.specification_enums import AspectRatio
from src.models.video_job import VideoJob
from src.models.visual_continuity import CanonicalEntityIdentity, CanonicalEntityType
from src.services.genre_visual_mood import visual_direction

# How much of the Style brief goes into an image prompt: enough to carry the medium, palette and rules, short
# enough for an image generator to read.
_BRIEF_CHARACTERS_IN_IMAGE_PROMPT = 1500


def automatic_references_enabled(job: VideoJob) -> bool:
    """False in manual mode: the app takes no reference frame by itself."""

    return job.reference_mode != ReferenceMode.MANUAL


def is_operator_picture(asset: IndexedAsset) -> bool:
    """A picture the operator uploaded or chose (not one the app picked by itself)."""

    return bool(
        asset.metadata.get("uploaded_by_operator")
        or asset.metadata.get("chosen_by_operator")
    )


def picture_is_attachable(job: VideoJob, asset: IndexedAsset) -> bool:
    """Whether `asset` may be attached to a scene under the project's reference mode."""

    return automatic_references_enabled(job) or is_operator_picture(asset)


def has_operator_picture(job: VideoJob, identity: CanonicalEntityIdentity) -> bool:
    for asset_id in identity.reference_asset_ids:
        try:
            asset = job.extracted_frame_asset_index.get(asset_id)
        except ValueError:
            continue

        if asset is not None and is_operator_picture(asset):
            return True

    return False


def scenes_of(job: VideoJob, name: str) -> list[int]:
    """The scenes a character or place is marked as on screen in."""

    bible = job.visual_continuity_bible

    if bible is None:
        return []

    return sorted(
        entry.scene_number
        for entry in bible.clip_entries
        if name in entry.on_screen_entity_names
    )


def set_scenes_of(job: VideoJob, name: str, scene_numbers: list[int]) -> None:
    """Mark `name` as on screen in exactly these scenes (added AND removed, unlike mark_scenes)."""

    bible = job.visual_continuity_bible

    if bible is None:
        raise ValueError("Generate the visual continuity bible first.")

    by_scene = {entry.scene_number: entry for entry in bible.clip_entries}
    unknown = [n for n in scene_numbers if n not in by_scene]

    if unknown:
        raise ValueError(
            f"Scene {unknown[0]} has no continuity entry - regenerate the visual continuity bible."
        )

    wanted = set(scene_numbers)

    for number, entry in by_scene.items():
        listed = name in entry.entity_names
        on_screen = name in entry.on_screen_entity_names

        if number in wanted:
            if not listed:
                entry.entity_names.append(name)

            if not on_screen:
                entry.on_screen_entity_names.append(name)
        else:
            entry.entity_names = [n for n in entry.entity_names if n != name]
            entry.on_screen_entity_names = [
                n for n in entry.on_screen_entity_names if n != name
            ]


def remove_from_scene(job: VideoJob, name: str, scene_number: int) -> None:
    """Stop showing `name` in this one scene (its other scenes and its picture are kept)."""

    bible = job.visual_continuity_bible

    if bible is None:
        return

    for entry in bible.clip_entries:
        if entry.scene_number == scene_number:
            entry.entity_names = [n for n in entry.entity_names if n != name]
            entry.on_screen_entity_names = [
                n for n in entry.on_screen_entity_names if n != name
            ]


def clear_picture(job: VideoJob, name: str) -> None:
    """Take the reference picture off a character or place (the stored file is kept)."""

    identity = _identity(job, name)
    identity.reference_asset_ids = []


@dataclass(frozen=True)
class MissingPicture:
    name: str
    scenes: list[int]


def missing_pictures(job: VideoJob) -> list[MissingPicture]:
    """Characters and places marked in at least one scene that have no picture from the operator."""

    bible = job.visual_continuity_bible

    if bible is None:
        return []

    missing: list[MissingPicture] = []

    for identity in bible.identities:
        scenes = scenes_of(job, identity.name)

        if scenes and not has_operator_picture(job, identity):
            missing.append(MissingPicture(name=identity.name, scenes=scenes))

    return missing


def reference_image_prompt(job: VideoJob, identity: CanonicalEntityIdentity) -> str:
    """Text to paste into an image generator to make this character's or place's reference picture, in
    the series' own style so the picture and the clips do not drift apart. Built from the identity's
    description, the project look and the Style brief - no model call."""

    style = _style_text(job)
    is_person = identity.entity_type == CanonicalEntityType.PERSON
    parts: list[str] = []

    if is_person:
        parts.append(f"Character reference picture of {identity.name}.")
        parts.append(identity.canonical_description.rstrip(".") + ".")

        if identity.outfit:
            parts.append(f"Outfit: {identity.outfit.rstrip('.')}.")

        parts.append(
            "Show the character alone, facing the camera, face clearly visible and well lit, "
            "neutral expression, upper body in frame, plain simple background, no other people, "
            "no props in the hands, no text."
        )
    else:
        parts.append(f"Place reference picture of {identity.name}.")
        parts.append(identity.canonical_description.rstrip(".") + ".")
        parts.append(
            "Show the place on its own, a wide clear view of the whole space, no people, "
            "even readable lighting, no text."
        )

    if style:
        parts.append(
            "Draw it in exactly the style of the series, so it matches the video: "
            + style
        )

    parts.append(
        f"Composition: {_orientation(job)} frame. Original artwork; do not imitate any "
        "existing work."
    )

    return " ".join(parts)


def _orientation(job: VideoJob) -> str:
    return (
        "vertical portrait (9:16)"
        if job.aspect_ratio == AspectRatio.PORTRAIT
        else "horizontal landscape (16:9)"
    )


def _style_text(job: VideoJob) -> str:
    """The series style for an image prompt: the look fields, then the operator's brief."""

    pieces: list[str] = []
    look = job.project_look

    if look is not None and not look.is_empty:
        sentence = look.as_prompt_sentence(universal_only=False)

        if sentence:
            pieces.append(sentence.rstrip("."))

    brief = " ".join(job.style_brief.split())

    if brief:
        pieces.append(brief[:_BRIEF_CHARACTERS_IN_IMAGE_PROMPT].rstrip())
    else:
        direction = visual_direction(job.genre_id)

        if direction:
            pieces.append(direction)

    return " ".join(pieces)


def _identity(job: VideoJob, name: str) -> CanonicalEntityIdentity:
    bible = job.visual_continuity_bible

    if bible is None:
        raise ValueError("There is no visual continuity bible.")

    for identity in bible.identities:
        if identity.name == name:
            return identity

    raise ValueError(f"There is no character or place named {name}.")
