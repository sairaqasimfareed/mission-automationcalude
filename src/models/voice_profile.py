from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, field_validator, model_validator

from src.models.base import MissionBaseModel
from src.models.voice_directives import (
    VoiceEmotion,
    VoiceEmphasisStyle,
    VoiceEnergy,
    VoicePace,
    VoicePauseStyle,
    VoicePitchStyle,
)


class VoiceProfileStatus(str, Enum):
    """Lifecycle status of one registered voice profile."""

    ACTIVE = "active"
    DEPRECATED = "deprecated"
    DISABLED = "disabled"


class VoiceProfile(MissionBaseModel):
    """
    Provider-independent reusable voice profile.

    This model stores normalized voice defaults and optional
    provider mappings, but never API credentials.
    """

    schema_version: str = "1.0"

    profile_id: str

    display_name: str

    description: str = ""

    version: str = "1.0.0"

    status: VoiceProfileStatus = VoiceProfileStatus.ACTIVE

    fallback_profile_id: str | None = "voice.neutral_narrator"

    emotion: VoiceEmotion = VoiceEmotion.NEUTRAL

    pace: VoicePace = VoicePace.MODERATE

    energy: VoiceEnergy = VoiceEnergy.MEDIUM

    pitch_style: VoicePitchStyle = VoicePitchStyle.NATURAL

    pause_style: VoicePauseStyle = VoicePauseStyle.NATURAL

    emphasis_style: VoiceEmphasisStyle = VoiceEmphasisStyle.BALANCED

    default_speed: float = Field(
        default=1.0,
        ge=0.5,
        le=2.0,
    )

    default_pitch_adjustment: float = Field(
        default=0.0,
        ge=-20.0,
        le=20.0,
    )

    default_volume_gain_db: float = Field(
        default=0.0,
        ge=-20.0,
        le=20.0,
    )

    default_stability: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
    )

    default_similarity_boost: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
    )

    default_style_strength: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
    )

    default_speaker_boost: bool = True

    provider_mappings: dict[
        str,
        dict[str, Any],
    ] = Field(
        default_factory=dict,
    )

    tags: list[str] = Field(
        default_factory=list,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(
        cls,
        value: str,
    ) -> str:
        return normalize_voice_profile_id(value)

    @field_validator("fallback_profile_id")
    @classmethod
    def validate_fallback_profile_id(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        return normalize_voice_profile_id(value)

    @field_validator(
        "display_name",
        "version",
    )
    @classmethod
    def clean_required_text(
        cls,
        value: str,
    ) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Voice profile text cannot be empty.")

        return cleaned

    @field_validator("description")
    @classmethod
    def clean_description(
        cls,
        value: str,
    ) -> str:
        return value.strip()

    @field_validator("tags")
    @classmethod
    def clean_tags(
        cls,
        values: list[str],
    ) -> list[str]:
        cleaned: list[str] = []

        for value in values:
            normalized = value.strip().lower()

            if normalized and normalized not in cleaned:
                cleaned.append(normalized)

        return cleaned

    @field_validator("provider_mappings")
    @classmethod
    def clean_provider_mappings(
        cls,
        mappings: dict[
            str,
            dict[str, Any],
        ],
    ) -> dict[str, dict[str, Any]]:
        cleaned: dict[
            str,
            dict[str, Any],
        ] = {}

        for provider_name, settings in mappings.items():
            normalized_name = provider_name.strip().lower()

            if not normalized_name:
                raise ValueError("Voice provider mapping name " "cannot be empty.")

            cleaned[normalized_name] = dict(settings)

        return cleaned

    @model_validator(mode="after")
    def validate_fallback(
        self,
    ) -> VoiceProfile:
        if self.fallback_profile_id == self.profile_id:
            raise ValueError("A voice profile cannot use itself " "as its fallback.")

        if (
            self.profile_id == "voice.neutral_narrator"
            and self.fallback_profile_id is not None
        ):
            raise ValueError(
                "The neutral narrator profile cannot " "declare another fallback."
            )

        return self

    @property
    def usable(self) -> bool:
        """Return whether this profile may be selected."""

        return self.status == VoiceProfileStatus.ACTIVE


class VoiceProfileResolutionResult(MissionBaseModel):
    """Result of resolving one requested voice profile."""

    requested_profile_id: str

    resolved_profile_id: str | None = None

    profile: VoiceProfile | None = None

    found_exact_match: bool = False
    used_fallback: bool = False

    warning: str | None = None

    @property
    def is_resolved(self) -> bool:
        """Return whether a usable voice profile was found."""

        return self.profile is not None


def normalize_voice_profile_id(
    value: str,
) -> str:
    """Normalize and validate one voice profile ID."""

    normalized = value.strip().lower()

    if not normalized:
        raise ValueError("Voice profile ID cannot be empty.")

    if not normalized.startswith("voice."):
        raise ValueError("Voice profile ID must start " "with 'voice.'.")

    if normalized == "voice.":
        raise ValueError("Voice profile ID requires a name.")

    allowed_characters = set("abcdefghijklmnopqrstuvwxyz" "0123456789._-")

    if any(character not in allowed_characters for character in normalized):
        raise ValueError("Voice profile ID contains " "unsupported characters.")

    return normalized
