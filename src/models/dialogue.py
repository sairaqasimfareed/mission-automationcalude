from __future__ import annotations

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel

MAX_SPEAKER_NAME_CHARACTERS = 60
# The voice that reads every line that names no speaker in a voice-cast script.
NARRATOR_NAME = "Narrator"
MAX_SPOKEN_LINE_CHARACTERS = 1200


class DialogueLine(MissionBaseModel):
    """
    One line spoken on camera by a named character (Character-Oriented Video mode,
    2026-10-09). The operator's own script is written as `NAME: line`; each such line
    becomes one of these, in order, on the scene that carries it.

    `text` is exactly what is said - no name, no quotation marks - because it also
    becomes the scene's narration, so the voice timing probe, clip sizing and the
    subtitles all work unchanged on the spoken words.
    """

    speaker: str = Field(min_length=1, max_length=MAX_SPEAKER_NAME_CHARACTERS)
    text: str = Field(min_length=1, max_length=MAX_SPOKEN_LINE_CHARACTERS)

    @field_validator("speaker", "text")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return " ".join(value.split())

    @property
    def word_count(self) -> int:
        return len(self.text.split())


def spoken_text(lines: list[DialogueLine]) -> str:
    """The words said in `lines`, in order, as one block of narration."""

    return " ".join(line.text for line in lines)


def speakers_in(lines: list[DialogueLine]) -> list[str]:
    """Who speaks in `lines`, each name once, in order of first appearance."""

    seen: list[str] = []

    for line in lines:
        if line.speaker not in seen:
            seen.append(line.speaker)

    return seen
