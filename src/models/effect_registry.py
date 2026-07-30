from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, field_validator, model_validator

from src.models.base import MissionBaseModel


class EffectCategory(str, Enum):
    """Supported effect-registry categories."""

    CAMERA = "camera"
    TRANSITION = "transition"
    VISUAL = "visual"
    ANIMATION = "animation"
    MUSIC = "music"
    SOUND_EFFECT = "sfx"
    SUBTITLE = "subtitle"
    GENRE = "genre"


class EffectPresetStatus(str, Enum):
    """Lifecycle status of one registered preset."""

    ACTIVE = "active"
    DEPRECATED = "deprecated"
    DISABLED = "disabled"


class EffectPreset(MissionBaseModel):
    """
    Provider-independent preset stored in the effect registry.

    The implementation field contains normalized configuration,
    not arbitrary executable commands.
    """

    preset_id: str
    category: EffectCategory

    display_name: str

    version: str = "1.0.0"

    status: EffectPresetStatus = (
        EffectPresetStatus.ACTIVE
    )

    fallback_preset_id: str | None = None

    implementation: dict[str, Any] = Field(
        default_factory=dict,
    )

    tags: list[str] = Field(
        default_factory=list,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator("preset_id")
    @classmethod
    def normalize_preset_id(
        cls,
        value: str,
    ) -> str:
        return normalize_effect_id(value)

    @field_validator("fallback_preset_id")
    @classmethod
    def normalize_fallback_preset_id(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        return normalize_effect_id(value)

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
            raise ValueError(
                "Effect preset text cannot be empty."
            )

        return cleaned

    @field_validator("tags")
    @classmethod
    def clean_tags(
        cls,
        values: list[str],
    ) -> list[str]:
        cleaned: list[str] = []

        for value in values:
            normalized = value.strip().lower()

            if (
                normalized
                and normalized not in cleaned
            ):
                cleaned.append(normalized)

        return cleaned

    @model_validator(mode="after")
    def validate_category_prefix(
        self,
    ) -> EffectPreset:
        expected_prefix = (
            f"{self.category.value}."
        )

        if not self.preset_id.startswith(
            expected_prefix
        ):
            raise ValueError(
                "Effect preset ID category does not "
                "match its registry category."
            )

        if (
            self.fallback_preset_id is not None
            and not self.fallback_preset_id.startswith(
                expected_prefix
            )
        ):
            raise ValueError(
                "Fallback preset must belong to the "
                "same effect category."
            )

        if (
            self.fallback_preset_id
            == self.preset_id
        ):
            raise ValueError(
                "An effect preset cannot use itself "
                "as its fallback."
            )

        return self

    @property
    def usable(self) -> bool:
        """Return whether the preset may be resolved."""

        return (
            self.status
            == EffectPresetStatus.ACTIVE
        )


class EffectResolutionResult(MissionBaseModel):
    """Result of resolving one requested effect ID."""

    requested_preset_id: str

    resolved_preset_id: str | None = None
    preset: EffectPreset | None = None

    found_exact_match: bool = False
    used_fallback: bool = False

    warning: str | None = None

    @property
    def is_resolved(self) -> bool:
        """Return whether a usable preset was resolved."""

        return self.preset is not None


def normalize_effect_id(
    value: str,
) -> str:
    """Normalize and validate a registry identifier."""

    normalized = value.strip().lower()

    if not normalized:
        raise ValueError(
            "Effect registry ID cannot be empty."
        )

    if "." not in normalized:
        raise ValueError(
            "Effect registry ID requires a "
            "category prefix."
        )

    allowed_characters = set(
        "abcdefghijklmnopqrstuvwxyz"
        "0123456789._-"
    )

    if any(
        character not in allowed_characters
        for character in normalized
    ):
        raise ValueError(
            "Effect registry ID contains "
            "unsupported characters."
        )

    prefix, name = normalized.split(
        ".",
        maxsplit=1,
    )

    valid_prefixes = {
        category.value
        for category in EffectCategory
    }

    if prefix not in valid_prefixes:
        raise ValueError(
            "Effect registry ID uses an "
            "unsupported category."
        )

    if not name:
        raise ValueError(
            "Effect registry ID requires a name."
        )

    return normalized