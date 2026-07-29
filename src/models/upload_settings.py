from __future__ import annotations

from enum import Enum

from pydantic import Field

from src.models.base import MissionBaseModel


class UploadPlatform(str, Enum):
    """Supported publishing platforms."""

    YOUTUBE = "youtube"
    FACEBOOK = "facebook"
    TIKTOK = "tiktok"
    INSTAGRAM = "instagram"
    CUSTOM = "custom"


class UploadVisibility(str, Enum):
    """Publishing visibility."""

    PRIVATE = "private"
    UNLISTED = "unlisted"
    PUBLIC = "public"
    SCHEDULED = "scheduled"


class UploadSettings(MissionBaseModel):
    """Publishing configuration."""

    schema_version: str = "1.0"

    platform: UploadPlatform = UploadPlatform.YOUTUBE

    visibility: UploadVisibility = UploadVisibility.PRIVATE

    auto_upload: bool = False

    publish_immediately: bool = False

    scheduled_publish_datetime: str | None = None

    playlist_name: str | None = None

    notify_subscribers: bool = True

    allow_comments: bool = True

    allow_embedding: bool = True

    made_for_kids: bool = False

    custom_thumbnail: bool = True

    upload_retry_count: int = Field(
        default=3,
        ge=0,
        le=10,
    )
