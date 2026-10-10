"""The operator's own on-screen visual for each scene, kept on the project.

Live, 2026-10-10 (Haunted wife): a script imported as plain narration gives a documentary - every step
that decides what a clip shows is told to describe only what the narration says, so nothing a viewer is
meant to SEE (a ghost, a creature, a half-seen figure) ever appears unless the narration names it. The
operator can write that visual themselves (or have another assistant write it) and paste it; it is stored
here and every step that decides what a scene shows treats it as an instruction, not a suggestion.

A visual belongs to one scene by number AND by the text of that scene's narration (`narration_key`):
scenes are rebuilt when the script changes, so a visual written for text that has since changed is
STALE and is shown as such rather than silently attached to different narration.
"""

from __future__ import annotations

import hashlib
import re
import uuid

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel
from src.models.scene import Scene

MAX_VISUAL_CHARACTERS = 1500


def normalize_text(text: str) -> str:
    """Lower-case words only, so curly quotes, capitals and punctuation never decide a match."""

    cleaned = (
        text.replace("’", "'")
        .replace("‘", "'")
        .replace("“", '"')
        .replace("”", '"')
        .lower()
    )

    return re.sub(r"[^a-z0-9]+", " ", cleaned).strip()


def narration_key(narration: str) -> str:
    """A short fingerprint of a scene's narration."""

    return hashlib.sha256(normalize_text(narration).encode("utf-8")).hexdigest()[:16]


class SceneVisual(MissionBaseModel):
    scene_number: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=MAX_VISUAL_CHARACTERS)
    narration_key: str = Field(min_length=1)
    # How many pasted rows were joined into this text (a scene made of several sentences can
    # receive more than one row).
    row_count: int = Field(default=1, ge=1)
    # True once the operator typed into it by hand after pasting.
    hand_edited: bool = False

    @field_validator("text")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return " ".join(value.split())


class SceneVisualPlan(MissionBaseModel):
    visuals: list[SceneVisual] = Field(default_factory=list)
    # Changes every time the visuals are saved, so an artifact built from an earlier set (the shot
    # plan) can tell it no longer reflects them.
    revision: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])

    def entry_for(self, scene_number: int) -> SceneVisual | None:
        for visual in self.visuals:
            if visual.scene_number == scene_number:
                return visual

        return None

    def current_text_for(self, scene_number: int, narration: str) -> str:
        """The visual for this scene, or "" when there is none or it was written for different
        narration."""

        entry = self.entry_for(scene_number)

        if entry is None or entry.narration_key != narration_key(narration):
            return ""

        return entry.text

    def current_texts(self, scenes: list[Scene]) -> dict[int, str]:
        """{scene number: visual} for every scene whose visual is still current."""

        found: dict[int, str] = {}

        for scene in scenes:
            text = self.current_text_for(scene.scene_number, scene.narration)

            if text:
                found[scene.scene_number] = text

        return found

    def stale_scene_numbers(self, scenes: list[Scene]) -> list[int]:
        """Scenes that hold a visual written for narration (or a scene number) that has
        changed since."""

        current = {scene.scene_number: scene.narration for scene in scenes}

        return sorted(
            visual.scene_number
            for visual in self.visuals
            if visual.scene_number not in current
            or visual.narration_key != narration_key(current[visual.scene_number])
        )
