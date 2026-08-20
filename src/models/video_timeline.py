from __future__ import annotations

from pydantic import Field

from src.models.base import MissionBaseModel
from src.models.video_clip import VideoClip
from src.models.video_timeline_item import (
    VideoTimelineItem,
)


class VideoTimeline(MissionBaseModel):
    """
    Represents the complete video editing timeline.

    The clips field remains available for backward compatibility.
    Timeline-aware workflows should use items.
    """

    clips: list[VideoClip] = Field(
        default_factory=list,
    )

    items: list[VideoTimelineItem] = Field(
        default_factory=list,
    )

    total_duration_seconds: float = 0.0

    output_resolution: str = "1920x1080"

    frame_rate: int = Field(
        default=30,
        ge=1,
        le=240,
    )

    output_file: str | None = None

    def calculate_duration(self) -> float:
        """Calculate and store the complete timeline duration."""

        if self.items:
            enabled_items = [item for item in self.items if item.enabled]

            if not enabled_items:
                self.total_duration_seconds = 0.0
            else:
                self.total_duration_seconds = max(
                    item.end_time_seconds for item in enabled_items
                )

            return self.total_duration_seconds

        self.total_duration_seconds = float(
            sum(clip.duration_seconds for clip in self.clips)
        )

        return self.total_duration_seconds

    def ordered_items(self) -> list[VideoTimelineItem]:
        """Return enabled timeline items in playback order."""

        return sorted(
            (item for item in self.items if item.enabled),
            key=lambda item: (
                item.start_time_seconds,
                item.track_index,
                item.layer_index,
                item.scene_number,
            ),
        )

    @property
    def has_timeline_items(self) -> bool:
        """Return whether the timeline uses explicit placements."""

        return bool(self.items)
