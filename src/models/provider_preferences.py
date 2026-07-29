from __future__ import annotations

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel


class ProviderPreference(MissionBaseModel):
    """Provider preference for one production category."""

    preferred_profile_id: str | None = None
    fallback_profile_ids: list[str] = Field(default_factory=list)
    auto_select: bool = True
    lock_preferred_provider: bool = False

    @field_validator("fallback_profile_ids")
    @classmethod
    def clean_fallback_profile_ids(
        cls,
        values: list[str],
    ) -> list[str]:
        cleaned: list[str] = []

        for value in values:
            normalized = value.strip()

            if not normalized:
                continue

            if normalized not in cleaned:
                cleaned.append(normalized)

        return cleaned


class ProviderPreferences(MissionBaseModel):
    """Project-level provider preferences by category."""

    schema_version: str = "1.0"

    llm: ProviderPreference = Field(
        default_factory=ProviderPreference
    )
    video: ProviderPreference = Field(
        default_factory=ProviderPreference
    )
    voice: ProviderPreference = Field(
        default_factory=ProviderPreference
    )
    image: ProviderPreference = Field(
        default_factory=ProviderPreference
    )
    stock_video: ProviderPreference = Field(
        default_factory=ProviderPreference
    )
    stock_image: ProviderPreference = Field(
        default_factory=ProviderPreference
    )
    music: ProviderPreference = Field(
        default_factory=ProviderPreference
    )
    sound_effects: ProviderPreference = Field(
        default_factory=ProviderPreference
    )
    upload: ProviderPreference = Field(
        default_factory=ProviderPreference
    )