from __future__ import annotations

from enum import Enum

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel


class AudienceAgeGroup(str, Enum):
    """Supported target audience age groups."""

    GENERAL = "general"
    CHILDREN = "children"
    TEENS = "teens"
    ADULTS = "adults"
    SENIORS = "seniors"


class AudienceSettings(MissionBaseModel):
    """Defines language, location, and audience targeting."""

    schema_version: str = "1.0"

    language: str = Field(
        default="English",
        min_length=2,
        max_length=100,
    )

    target_country: str = Field(
        default="United States",
        min_length=2,
        max_length=100,
    )

    target_audience: str = Field(
        default="General audience",
        min_length=2,
        max_length=300,
    )

    age_group: AudienceAgeGroup = AudienceAgeGroup.GENERAL

    localization_enabled: bool = False

    localization_notes: str = Field(
        default="",
        max_length=1000,
    )

    cultural_requirements: list[str] = Field(
        default_factory=list
    )

    excluded_topics: list[str] = Field(
        default_factory=list
    )

    @field_validator(
        "language",
        "target_country",
        "target_audience",
    )
    @classmethod
    def clean_required_text(
        cls,
        value: str,
    ) -> str:
        value = value.strip()

        if not value:
            raise ValueError(
                "Audience text fields cannot be empty."
            )

        return value

    @field_validator(
        "cultural_requirements",
        "excluded_topics",
    )
    @classmethod
    def clean_text_lists(
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