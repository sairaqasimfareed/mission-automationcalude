from __future__ import annotations

from enum import Enum

from pydantic import field_validator

from src.models.base import MissionBaseModel


class ManualAudioRequirementType(str, Enum):
    """Which audio component a human must supply manually."""

    VOICE = "voice"
    MUSIC = "music"
    SOUND_EFFECT = "sound_effect"


class ManualAudioRequirement(MissionBaseModel):
    """
    One audio component that generation cannot produce automatically
    (e.g. no provider configured) - an explicit, actionable
    requirement rather than an ambiguous RuntimeError message.
    """

    requirement_type: ManualAudioRequirementType
    reason: str
    instructions: str

    fulfilled: bool = False
    provided_file: str | None = None

    @field_validator("reason", "instructions")
    @classmethod
    def clean_required_text(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Manual audio requirement text cannot be empty.")

        return cleaned
