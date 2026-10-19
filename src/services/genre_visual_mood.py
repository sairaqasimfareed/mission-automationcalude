"""How a genre should FEEL on screen, as direction for the steps that decide the look.

Live, 2026-10-10 (Haunted wife, genre.horror): the video came out as a calm documentary. Nothing told
the steps that write the look about the genre - the style sheet drafter was even given "documentary"
as its example of camera language, and shot planning never saw the genre at all. So a horror script
got documentary framing and the same even coverage as a history explainer.

`genre_direction` is one short paragraph per genre, handed to the style sheet drafter, shot planning
and the scene detail writer as TREATMENT: how to light, frame and sound what the script already says.
It never adds an event, person or object (the rules of each step still forbid that). A genre whose
default look is already right - and `genre.default` - has no direction, and a step that gets "" behaves
exactly as before.

`genre_style_defaults` fills the style fields (lighting, palette, camera feel, sound) a script gave
nothing for. It never touches setting, buildings or climate: those are facts about the script's world.
The lighting, palette and camera come from the genre's first ready-made look (the same table the
operator's look suggestions use - one source, not a second copy); the sound is the genre's own.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.services.project_look_suggestion_service import _GENRE_LOOKS


@dataclass(frozen=True)
class GenreVisualMood:
    direction: str
    sound: str


_MOODS: dict[str, GenreVisualMood] = {
    "genre.horror": GenreVisualMood(
        direction=(
            "Cinematic dread, NOT documentary. Motivated low light with deep shadow and dark "
            "corners; negative space; a threat suggested, never fully shown - something half "
            "seen at the edge of the frame, a shape in the dark, a detail that is slightly "
            "wrong. Slow creeping camera and long held frames that make the viewer search the "
            "image. Keep the unsettling element recurring in small, ambiguous ways."
        ),
        sound="faint low hum, creaks, held silences and sudden stillness; no music",
    ),
    "genre.mystery": GenreVisualMood(
        direction=(
            "Noir mystery. Low-key light with strong contrast and long shadows; clues "
            "present in the frame but not explained; faces and key objects partly obscured "
            "until the narration reveals them; deliberate, patient camera."
        ),
        sound="muted room tone, a distant clock or footsteps, long silences; no music",
    ),
    "genre.documentary": GenreVisualMood(
        direction=(
            "Observational realism. Natural light, real places and objects, a camera that "
            "watches rather than stages; nothing dramatised beyond what the narration says."
        ),
        sound="natural ambient sound of the place; no music",
    ),
    "genre.history": GenreVisualMood(
        direction=(
            "Sober and period-faithful. Painterly, composed frames; light and materials true "
            "to the era; slow push-ins on objects and places of the past; the weight of time "
            "in worn surfaces rather than spectacle."
        ),
        sound="quiet period ambience: wind, stone, distant voices; no music",
    ),
    "genre.survival": GenreVisualMood(
        direction=(
            "Gritty and urgent. Hard natural light, handheld proximity to the subject, the "
            "scale of the land or weather against a small figure; effort and exposure visible "
            "on faces, hands and gear."
        ),
        sound="wind, breath, boots on ground, water or fire; no music",
    ),
    "genre.storytelling": GenreVisualMood(
        direction=(
            "Intimate and human. Warm practical light, human-level camera, close framing on "
            "faces, hands and small meaningful objects; emotion carried by the image, not by "
            "movement."
        ),
        sound="soft room tone and the sounds of everyday life; no music",
    ),
}

# Genres not listed (genre.default, medical, travel, top10, reaction, comedy) are steered by their
# own presets already and get no direction here.


def genre_direction(genre_id: str) -> str:
    """The treatment direction for the genre, or "" when it has none."""

    mood = _MOODS.get(genre_id)

    return mood.direction if mood is not None else ""


_STYLE_BRIEF_MAX_CHARACTERS = 6000


def visual_direction(genre_id: str, style_brief: str = "") -> str:
    """What every visual step is told about the video's look: the genre's treatment direction, then
    the operator's own style brief (binding - it wins where the two differ). "" when neither exists.
    """

    direction = genre_direction(genre_id)
    brief = " ".join(style_brief.split())[:_STYLE_BRIEF_MAX_CHARACTERS]

    if not brief:
        return direction

    brief_block = (
        "STYLE BRIEF FROM THE OPERATOR - binding for this whole video; follow it, and where it differs "
        f"from the genre direction it wins: {brief} "
        "A different palette for one kind of scene (a flashback, a night scene, a verdict) is only a "
        "colour GRADE of the same look: keep the same drawing style, line quality, contrast, "
        "shadows and framing, and change only the colour."
    )

    return direction + "\n\n" + brief_block if direction else brief_block


def genre_style_defaults(genre_id: str) -> dict[str, str]:
    """Style fields (ProjectLook names) to use where the script gave nothing; {} for a
    genre with no mood."""

    mood = _MOODS.get(genre_id)
    looks = _GENRE_LOOKS.get(genre_id)

    if mood is None or not looks:
        return {}

    _label, lighting, palette, camera = looks[0]

    return {
        "lighting": lighting,
        "color_palette": palette,
        "camera_feel": camera,
        "sound": mood.sound,
    }
