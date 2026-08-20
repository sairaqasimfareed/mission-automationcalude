from __future__ import annotations

from enum import Enum

from pydantic import Field

from src.models.base import MissionBaseModel


class TimelineValidationSeverity(str, Enum):
    """Severity level for one timeline validation issue."""

    WARNING = "warning"
    ERROR = "error"


class TimelineValidationCode(str, Enum):
    """Supported timeline validation issue types."""

    NO_ITEMS = "no_items"
    DUPLICATE_SCENE = "duplicate_scene"
    TIMELINE_GAP = "timeline_gap"
    TIMELINE_OVERLAP = "timeline_overlap"
    INVALID_DURATION = "invalid_duration"
    CLIP_DURATION_MISMATCH = "clip_duration_mismatch"
    CLIP_NOT_READY = "clip_not_ready"
    MISSING_CLIP_SOURCE = "missing_clip_source"

    MISSING_EDITING_BLUEPRINT = "missing_editing_blueprint"

    UNRESOLVED_EDITING_BLUEPRINT = "unresolved_editing_blueprint"

    EDITING_BLUEPRINT_SCENE_MISMATCH = "editing_blueprint_scene_mismatch"

    EDITING_BLUEPRINT_FALLBACK_USED = "editing_blueprint_fallback_used"


class TimelineValidationIssue(MissionBaseModel):
    """One warning or error discovered during validation."""

    code: TimelineValidationCode
    severity: TimelineValidationSeverity

    message: str

    scene_number: int | None = None
    related_scene_number: int | None = None

    start_time_seconds: float | None = None
    end_time_seconds: float | None = None

    metadata: dict = Field(
        default_factory=dict,
    )


class TimelineValidationResult(MissionBaseModel):
    """Complete validation report for one video timeline."""

    is_valid: bool

    errors: list[TimelineValidationIssue] = Field(
        default_factory=list,
    )

    warnings: list[TimelineValidationIssue] = Field(
        default_factory=list,
    )

    item_count: int = 0
    enabled_item_count: int = 0
    track_count: int = 0

    total_duration_seconds: float = 0.0

    gap_duration_seconds: float = 0.0
    overlap_duration_seconds: float = 0.0

    blueprint_count: int = 0

    render_ready_item_count: int = 0

    blueprint_fallback_count: int = 0

    @property
    def issue_count(self) -> int:
        """Return the total number of validation issues."""

        return len(self.errors) + len(self.warnings)

    @property
    def all_enabled_items_render_ready(
        self,
    ) -> bool:
        """Return whether all enabled items are render-ready."""

        return (
            self.enabled_item_count > 0
            and self.render_ready_item_count == self.enabled_item_count
        )
