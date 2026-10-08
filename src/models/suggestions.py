"""Suggestions the app makes on its own, for the operator to accept or discard.

The project look and the recurring characters/places used to be blank forms the
operator had to fill by hand (live, 2026-10-07: they cannot - they must be proposed).
Each suggestion keeps its status on the project, so it survives a restart and a
discarded one is not proposed again.
"""

from __future__ import annotations

from enum import Enum

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel
from src.models.visual_continuity import CanonicalEntityType


class SuggestionStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DISCARDED = "discarded"


class LookSuggestion(MissionBaseModel):
    """One candidate project look: lighting, colour palette and camera feel."""

    label: str = Field(min_length=1, max_length=80)
    lighting: str = ""
    color_palette: str = ""
    camera_feel: str = ""
    # Where it came from: "genre" (a ready-made look for the project's genre) or
    # "clips" (measured from the footage generated so far).
    source: str = "genre"
    status: SuggestionStatus = SuggestionStatus.PENDING

    @field_validator("label", "lighting", "color_palette", "camera_feel")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return " ".join(value.split())

    @property
    def key(self) -> str:
        """What makes two suggestions the same one (so it is not proposed twice)."""

        return " | ".join(
            part.lower()
            for part in (self.lighting, self.color_palette, self.camera_feel)
        )


class IdentitySuggestion(MissionBaseModel):
    """One candidate recurring character or place, with the scenes it appears in."""

    name: str = Field(min_length=1, max_length=60)
    kind: CanonicalEntityType
    description: str = Field(min_length=1, max_length=1200)
    scene_numbers: list[int] = Field(default_factory=list)
    status: SuggestionStatus = SuggestionStatus.PENDING

    @field_validator("name", "description")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return " ".join(value.split())

    @property
    def key(self) -> str:
        return self.name.lower()
