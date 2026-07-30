from __future__ import annotations

from pydantic import Field, model_validator

from src.models.base import MissionBaseModel
from src.models.video_clip import VideoClip


class VideoTimelineItem(MissionBaseModel):
    """Placement of one video clip on the editing timeline."""

    clip: VideoClip

    scene_number: int = Field(
        ge=1,
    )

    start_time_seconds: float = Field(
        default=0.0,
        ge=0.0,
    )

    end_time_seconds: float = Field(
        ge=0.0,
    )

    track_index: int = Field(
        default=0,
        ge=0,
    )

    layer_index: int = Field(
        default=0,
        ge=0,
    )

    enabled: bool = True

    transition_in: str | None = None
    transition_out: str | None = None

    metadata: dict = Field(
        default_factory=dict,
    )

    @model_validator(mode="after")
    def validate_timeline_item(
        self,
    ) -> VideoTimelineItem:
        if self.scene_number != self.clip.scene_number:
            raise ValueError(
                "Timeline item scene number must match "
                "the video clip scene number."
            )

        if self.end_time_seconds <= self.start_time_seconds:
            raise ValueError(
                "Timeline item end time must be greater "
                "than its start time."
            )

        expected_duration = float(
            self.clip.duration_seconds
        )

        actual_duration = (
            self.end_time_seconds
            - self.start_time_seconds
        )

        if abs(actual_duration - expected_duration) > 0.001:
            raise ValueError(
                "Timeline item duration must match "
                "the video clip duration."
            )

        return self

    @property
    def duration_seconds(self) -> float:
        """Return the timeline duration of this item."""

        return (
            self.end_time_seconds
            - self.start_time_seconds
        )