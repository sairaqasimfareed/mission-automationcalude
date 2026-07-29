from __future__ import annotations

from pydantic import Field, model_validator

from src.models.base import MissionBaseModel
from src.models.specification_enums import VisualStrategy


class VisualSettings(MissionBaseModel):
    """Controls project-level visual production preferences."""

    schema_version: str = "1.0"

    strategy: VisualStrategy = VisualStrategy.HYBRID

    allow_scene_strategy_override: bool = True

    prefer_local_assets: bool = True
    reuse_existing_assets: bool = True

    allow_stock_search: bool = True
    require_user_stock_approval: bool = True

    allow_manual_upload: bool = True
    allow_image_to_video: bool = True
    allow_ai_video_generation: bool = False

    local_asset_directory: str = "assets"

    stock_search_limit: int = Field(
        default=10,
        ge=1,
        le=100,
    )

    default_clip_duration_seconds: int = Field(
        default=8,
        ge=1,
        le=300,
    )

    default_transition_duration_seconds: float = Field(
        default=0.5,
        ge=0.0,
        le=10.0,
    )

    @model_validator(mode="after")
    def validate_visual_settings(self) -> "VisualSettings":
        """Prevent contradictory visual configuration states."""

        if (
            self.strategy == VisualStrategy.LOCAL_LIBRARY
            and not self.prefer_local_assets
        ):
            raise ValueError(
                "Local Library strategy requires "
                "prefer_local_assets to be enabled."
            )

        if (
            self.strategy == VisualStrategy.STOCK_FOOTAGE
            and not self.allow_stock_search
        ):
            raise ValueError(
                "Stock Footage strategy requires "
                "allow_stock_search to be enabled."
            )

        if (
            self.strategy == VisualStrategy.MANUAL_UPLOAD
            and not self.allow_manual_upload
        ):
            raise ValueError(
                "Manual Upload strategy requires "
                "allow_manual_upload to be enabled."
            )

        if (
            self.strategy == VisualStrategy.IMAGE_TO_VIDEO
            and not self.allow_image_to_video
        ):
            raise ValueError(
                "Image-to-Video strategy requires "
                "allow_image_to_video to be enabled."
            )

        if (
            self.strategy == VisualStrategy.AI_VIDEO
            and not self.allow_ai_video_generation
        ):
            raise ValueError(
                "AI Video strategy requires "
                "allow_ai_video_generation to be enabled."
            )

        if (
            self.strategy == VisualStrategy.HYBRID
            and not any(
                [
                    self.prefer_local_assets,
                    self.allow_stock_search,
                    self.allow_manual_upload,
                    self.allow_image_to_video,
                    self.allow_ai_video_generation,
                ]
            )
        ):
            raise ValueError(
                "Hybrid strategy requires at least one "
                "enabled visual source."
            )

        if not self.local_asset_directory.strip():
            raise ValueError(
                "local_asset_directory cannot be empty."
            )

        if (
            self.default_transition_duration_seconds
            >= self.default_clip_duration_seconds
        ):
            raise ValueError(
                "Default transition duration must be shorter "
                "than default clip duration."
            )

        return self