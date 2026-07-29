from __future__ import annotations

from enum import Enum

from pydantic import Field, model_validator

from src.models.base import MissionBaseModel
from src.models.media_strategy import (
    SceneSourceStatus,
    SceneSourceType,
)


class VideoClipStatus(str, Enum):
    PENDING = "pending"
    ACQUIRING = "acquiring"
    READY = "ready"
    FAILED = "failed"


class VideoClip(MissionBaseModel):
    """Standard visual clip returned by every visual source provider."""

    scene_number: int
    source_type: SceneSourceType

    duration_seconds: int
    prompt: str = ""

    provider: str | None = None
    source_url: str | None = None
    local_file: str | None = None

    license_type: str | None = None
    resolution: str = "1920x1080"
    aspect_ratio: str = "16:9"

    acquisition_time_seconds: float = 0.0
    estimated_cost: float = 0.0

    source_status: SceneSourceStatus = SceneSourceStatus.PENDING
    status: VideoClipStatus = VideoClipStatus.PENDING

    warnings: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_clip_source(self) -> "VideoClip":
        """Ensure a ready clip has a usable file or URL."""

        if self.source_type == SceneSourceType.AI_GENERATE:
            if self.source_status != SceneSourceStatus.DISABLED:
                raise ValueError(
                    "AI-generated video clips must remain disabled."
                )

        if self.status == VideoClipStatus.READY:
            if not self.local_file and not self.source_url:
                raise ValueError(
                    "A ready video clip requires local_file or source_url."
                )

        return self