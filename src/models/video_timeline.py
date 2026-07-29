from __future__ import annotations

from pydantic import Field

from src.models.base import MissionBaseModel
from src.models.video_clip import VideoClip


class VideoTimeline(MissionBaseModel):
    """
    Represents the complete sequence of generated video clips.
    """

    clips: list[VideoClip] = Field(default_factory=list)

    total_duration_seconds: int = 0

    output_resolution: str = "1920x1080"

    frame_rate: int = 30

    output_file: str | None = None

    def calculate_duration(self) -> int:
        self.total_duration_seconds = sum(clip.duration_seconds for clip in self.clips)

        return self.total_duration_seconds
