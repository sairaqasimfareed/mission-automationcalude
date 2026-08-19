from __future__ import annotations

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel


class PackagingHypothesis(MissionBaseModel):
    """
    An early, thin hypothesis for how a finished video should be
    packaged - not the final title/thumbnail work itself. That stays
    downstream, reusing the existing ThumbnailConceptGenerationService
    and SEOTitleGenerationService once the script is final; this model
    only captures the strategic direction those later, more expensive
    passes should follow, and gives a human something to review before
    they run.
    """

    topic: str = Field(min_length=1)
    genre_id: str = Field(min_length=1)

    viewer_promise: str = Field(min_length=1)
    title_territories: list[str] = Field(min_length=1)
    thumbnail_concepts: list[str] = Field(min_length=1)
    curiosity_mechanism: str = Field(min_length=1)
    expected_emotion: str = Field(min_length=1)
    differentiation_angle: str = Field(min_length=1)

    prompt_version: str = Field(min_length=1)

    @field_validator("genre_id")
    @classmethod
    def validate_genre_id(cls, value: str) -> str:
        normalized = value.strip().lower()

        if not normalized.startswith("genre."):
            raise ValueError("Genre ID must start with 'genre.'.")

        return normalized

    @field_validator("title_territories", "thumbnail_concepts")
    @classmethod
    def clean_text_list(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []

        for value in values:
            stripped = value.strip()

            if stripped and stripped not in cleaned:
                cleaned.append(stripped)

        if not cleaned:
            raise ValueError("Packaging hypothesis requires at least one entry.")

        return cleaned
