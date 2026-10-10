"""The words of a clip's prompt that make characters speak on camera.

Copied from the prompts that worked on Muse (operator's live tests, 2026-10-08): lip sync was
correct, a character's face, outfit and voice stayed the same across scenes with a reference picture
plus a repeated continuity sentence, and two characters in one scene kept two different voices with
correct turn-taking. The wording is therefore fixed text, not something rewritten per scene:

- each line is attributed - `<Name> says clearly in their own voice: "..."` - in the order spoken;
- the lips move in sync with the speech, and the audio is real speech with only quiet ambient sound,
  no music (the voiceover is muted at the mix; the clip's own audio is the speech);
- a scene with two or more speakers says only one speaks at a time, the listener's mouth stays closed,
  each keeps their own voice, and faces are three-quarter to the camera (a profile makes a useless
  reference picture and hides the lips);
- a speaker who already appeared is told to keep the same face and voice, continuing directly from the
  previous scene.

"Their" is deliberate: a name says nothing about who someone is, and the tested "his own voice" is not
guessed at. The character's appearance and outfit come from the character's own description, repeated in
every prompt they are in.
"""

from __future__ import annotations

from src.models.dialogue import DialogueLine, speakers_in
from src.models.scene import Scene

# Every sentence that carries the continuity request contains this; the completeness check does not
# count it as the relative wording it would otherwise be (it is a deliberate instruction, resolved by
# the reference picture and the earlier clips).
CONTINUITY_MARKER = "continuing directly from the previous scene"

_OUTDOOR_WORDS = (
    "outdoor",
    "outside",
    "street",
    "field",
    "forest",
    "woods",
    "lake",
    "shore",
    "beach",
    "road",
    "village",
    "platform",
    "yard",
    "garden",
    "porch",
    "hill",
    "mountain",
    "river",
    "desert",
    "square",
    "market",
    "countryside",
    "valley",
)

_NUMBER_WORDS = {2: "Two", 3: "Three", 4: "Four"}


# Muse ignores an attached picture unless the prompt tells it to use it (live, 2026-10-08), so a
# speaking scene that has a character's picture attached says so. Added at submission, when the
# pictures are known - the prompt is compiled before any clip, and so any picture, exists.
REFERENCE_PICTURE_SENTENCE = (
    "Same character as the attached reference image: same face, same voice."
)
MULTIPLE_REFERENCE_PICTURES_SENTENCE = (
    "Each speaker is the same character as in their attached reference image: "
    "same face, same voice."
)


def with_reference_picture_sentence(prompt: str, *, character_pictures: int) -> str:
    """`prompt` with the sentence that tells Muse to use the attached character picture(s),
    once; unchanged when no character picture is attached."""

    if character_pictures <= 0:
        return prompt

    sentence = (
        REFERENCE_PICTURE_SENTENCE
        if character_pictures == 1
        else MULTIPLE_REFERENCE_PICTURES_SENTENCE
    )

    if sentence in prompt:
        return prompt

    return f"{prompt.rstrip()} {sentence}"


def ambient_sound_for(environment: str) -> str:
    """ "quiet outdoor sound" for an outdoor setting, else the tested "quiet room sound"."""

    lowered = environment.lower()

    if any(word in lowered for word in _OUTDOOR_WORDS):
        return "quiet outdoor sound"

    return "quiet room sound"


def speakers_before(scenes: list[Scene], scene_number: int) -> set[str]:
    """Everyone who speaks in a scene before `scene_number`."""

    return {
        line.speaker
        for scene in scenes
        if scene.scene_number < scene_number
        for line in scene.dialogue
    }


def _says(line: DialogueLine, *, first: bool) -> str:
    lead = "" if first else "Then "

    return f'{lead}{line.speaker} says clearly in their own voice: "{line.text}"'


def dialogue_prompt_text(
    lines: list[DialogueLine],
    *,
    earlier_speakers: set[str] | None = None,
    environment: str = "",
    voices: dict[str, str] | None = None,
) -> str:
    """The speaking sentences for one scene, or "" for a scene with no dialogue."""

    if not lines:
        return ""

    earlier = earlier_speakers or set()
    speakers = speakers_in(lines)
    several = len(speakers) > 1
    parts: list[str] = []

    if several:
        count = _NUMBER_WORDS.get(len(speakers), "Several")
        parts.append(f"{count} people speak in this scene, in this order.")

    for index, line in enumerate(lines):
        parts.append(_says(line, first=index == 0))

    # Each speaker's own voice, written once for the character and repeated word for word: it is
    # what keeps a voice the same from clip to clip, and two voices apart in one clip.
    for speaker in speakers:
        voice = (voices or {}).get(speaker, "").strip().rstrip(".")

        if voice:
            parts.append(f"{speaker}'s voice: {voice}.")

    if several:
        faces = "Both faces are" if len(speakers) == 2 else "All faces are"
        parts.append(
            "Only one person speaks at a time; the listener's mouth stays closed. "
            "Each person keeps exactly their own voice throughout. "
            f"{faces} three-quarter to the camera. "
            "Each speaker's lips move naturally in sync with their own words."
        )
    else:
        parts.append("Their lips move naturally in sync with the speech.")

    parts.append(
        f"Real spoken audio with only {ambient_sound_for(environment)}, no music."
    )

    returning = [name for name in speakers if name in earlier]

    if returning and not several:
        parts.append(f"Same face, same voice, {CONTINUITY_MARKER}.")
    elif returning:
        who = " and ".join(returning)
        verb = "keeps" if len(returning) == 1 else "keep"
        parts.append(
            f"{who} {verb} the same face and the same voice, {CONTINUITY_MARKER}."
        )

    return " ".join(parts)
