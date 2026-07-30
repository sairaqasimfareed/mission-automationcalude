from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field

from src.models.base import MissionBaseModel
from src.models.editing_directives import (
    SceneEditingDirectives,
)
from src.models.resolved_editing_blueprint import (
    ResolvedSceneEditingBlueprint,
)
from src.models.timeline_validation import (
    TimelineValidationResult,
)
from src.models.video_timeline import VideoTimeline


class GenreTimelinePipelineStatus(str, Enum):
    """Lifecycle state of one genre timeline pipeline run."""

    COMPLETED = "completed"

    COMPLETED_WITH_WARNINGS = (
        "completed_with_warnings"
    )

    FAILED = "failed"


class GenreTimelinePipelineResult(
    MissionBaseModel
):
    """
    Result of building a genre-aware, render-ready timeline.

    Intermediate directives and resolved blueprints are retained
    for review, debugging, UI display, and future rendering.
    """

    requested_genre_id: str

    status: GenreTimelinePipelineStatus

    timeline: VideoTimeline

    directives: list[
        SceneEditingDirectives
    ] = Field(
        default_factory=list,
    )

    blueprints: list[
        ResolvedSceneEditingBlueprint
    ] = Field(
        default_factory=list,
    )

    validation: TimelineValidationResult

    warnings: list[str] = Field(
        default_factory=list,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @property
    def is_successful(self) -> bool:
        """Return whether the complete pipeline succeeded."""

        return self.status in {
            GenreTimelinePipelineStatus.COMPLETED,
            (
                GenreTimelinePipelineStatus
                .COMPLETED_WITH_WARNINGS
            ),
        }

    @property
    def is_render_ready(self) -> bool:
        """Return whether the resulting timeline may be rendered."""

        return (
            self.is_successful
            and self.validation.is_valid
            and (
                self.validation
                .all_enabled_items_render_ready
            )
        )

    @property
    def scene_count(self) -> int:
        """Return the number of processed scenes."""

        return len(self.directives)

    @property
    def fallback_count(self) -> int:
        """Return total effect fallback count."""

        return sum(
            blueprint.fallback_count
            for blueprint in self.blueprints
        )