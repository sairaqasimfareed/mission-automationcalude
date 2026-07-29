from __future__ import annotations

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel


class GeneralSettings(MissionBaseModel):
    """
    General information describing one Mission Automation project.
    """

    schema_version: str = "1.0"

    project_name: str = Field(
        min_length=3,
        max_length=150,
    )

    channel_name: str = Field(
        min_length=1,
        max_length=150,
    )

    topic: str = Field(
        min_length=3,
        max_length=300,
    )

    description: str = ""

    video_type: str = Field(
        min_length=1,
        max_length=100,
    )

    tags: list[str] = Field(default_factory=list)

    internal_notes: str = ""

    @field_validator(
        "project_name",
        "channel_name",
        "topic",
        "video_type",
    )
    @classmethod
    def validate_required_text(
        cls,
        value: str,
    ) -> str:
        value = value.strip()

        if not value:
            raise ValueError(
                "Field cannot be empty."
            )

        return value

    @field_validator("tags")
    @classmethod
    def validate_tags(
        cls,
        tags: list[str],
    ) -> list[str]:
        cleaned: list[str] = []

        for tag in tags:
            tag = tag.strip()

            if not tag:
                continue

            if tag not in cleaned:
                cleaned.append(tag)

        return cleaned

    @property
    def tag_count(self) -> int:
        return len(self.tags)