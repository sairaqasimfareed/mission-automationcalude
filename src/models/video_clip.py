from __future__ import annotations

from enum import Enum

from pydantic import Field

from src.models.base import MissionBaseModel


class VideoClipStatus(str, Enum):
    PENDING = "pending"
    GENERATING = "generating"
    GENERATED = "generated"
    FAILED = "failed"


class VideoClip(MissionBaseModel):
    """
    Represents one AI-generated video clip.
    """

    scene_number: int

    prompt: str

    duration_seconds: int

    provider: str = "Google Veo"

    model_name: str = "veo"

    output_file: str | None = None

    generation_time_seconds: float = 0.0

    cost_credits: int = 0

    status: VideoClipStatus = VideoClipStatus.PENDING

    metadata: dict = Field(default_factory=dict)