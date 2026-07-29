from __future__ import annotations

from pydantic import Field, model_validator

from src.models.base import MissionBaseModel


class PackagingSettings(MissionBaseModel):
    """Controls publish-ready packaging for one video project."""

    schema_version: str = "1.0"

    enabled: bool = True

    title_variant_count: int = Field(
        default=5,
        ge=1,
        le=20,
    )

    thumbnail_variant_count: int = Field(
        default=3,
        ge=0,
        le=10,
    )

    generate_description: bool = True
    generate_keywords: bool = True
    generate_tags: bool = True
    generate_hashtags: bool = True
    generate_chapters: bool = True
    generate_platform_captions: bool = True

    require_title_approval: bool = True
    require_thumbnail_approval: bool = True
    require_final_packaging_approval: bool = True

    allow_manual_title: bool = True
    allow_manual_thumbnail: bool = True
    allow_manual_description: bool = True

    preferred_llm_provider_profile_id: str | None = None
    preferred_image_provider_profile_id: str | None = None
    preferred_seo_provider_profile_id: str | None = None

    @model_validator(mode="after")
    def validate_packaging_settings(
        self,
    ) -> "PackagingSettings":
        """Prevent contradictory packaging configuration."""

        if not self.enabled:
            if self.require_title_approval:
                raise ValueError(
                    "Disabled packaging cannot require "
                    "title approval."
                )

            if self.require_thumbnail_approval:
                raise ValueError(
                    "Disabled packaging cannot require "
                    "thumbnail approval."
                )

            if self.require_final_packaging_approval:
                raise ValueError(
                    "Disabled packaging cannot require "
                    "final packaging approval."
                )

        if (
            self.thumbnail_variant_count == 0
            and self.require_thumbnail_approval
        ):
            raise ValueError(
                "Thumbnail approval requires at least one "
                "thumbnail variant."
            )

        return self

    @property
    def requires_user_review(self) -> bool:
        """Return whether packaging requires user approval."""

        if not self.enabled:
            return False

        return any(
            [
                self.require_title_approval,
                self.require_thumbnail_approval,
                self.require_final_packaging_approval,
            ]
        )