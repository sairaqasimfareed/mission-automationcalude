from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from src.models.base import MissionBaseModel
from src.models.resolved_editing_blueprint import (
    ResolvedSceneEditingBlueprint,
)
from src.models.video_clip import VideoClip


class VideoTimelineItem(MissionBaseModel):
    """
    Placement of one video clip on the editing timeline.

    The optional editing_blueprint contains the resolved,
    provider-independent editing instructions for this scene.

    transition_in and transition_out remain available for
    backward compatibility and quick timeline inspection.
    """

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

    editing_blueprint: (
        ResolvedSceneEditingBlueprint | None
    ) = None

    metadata: dict[str, Any] = Field(
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

        if (
            self.end_time_seconds
            <= self.start_time_seconds
        ):
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

        if (
            abs(
                actual_duration
                - expected_duration
            )
            > 0.001
        ):
            raise ValueError(
                "Timeline item duration must match "
                "the video clip duration."
            )

        if self.editing_blueprint is not None:
            if (
                self.editing_blueprint.scene_number
                != self.scene_number
            ):
                raise ValueError(
                    "Editing blueprint scene number must "
                    "match the timeline item scene number."
                )

            if not self.editing_blueprint.is_resolved:
                raise ValueError(
                    "Timeline items require a resolved "
                    "editing blueprint."
                )

        return self

    @property
    def duration_seconds(self) -> float:
        """Return the timeline duration of this item."""

        return (
            self.end_time_seconds
            - self.start_time_seconds
        )

    @property
    def has_editing_blueprint(self) -> bool:
        """Return whether resolved editing instructions exist."""

        return self.editing_blueprint is not None

    @property
    def is_render_ready(self) -> bool:
        """
        Return whether the item has a usable clip and blueprint.

        This property represents editing readiness. It does not
        replace complete timeline validation.
        """

        return (
            self.enabled
            and self.editing_blueprint is not None
            and self.editing_blueprint.is_resolved
        )