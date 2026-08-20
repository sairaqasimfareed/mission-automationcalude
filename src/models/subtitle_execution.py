from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, field_validator, model_validator

from src.models.base import MissionBaseModel


class SubtitleTimingSource(str, Enum):
    """Source used to determine subtitle timing."""

    ESTIMATED = "estimated"
    PRECISE = "precise"


class SubtitleExecutionStatus(str, Enum):
    """Lifecycle state of one subtitle execution."""

    PLANNED = "planned"
    VALIDATED = "validated"
    READY = "ready"
    APPLIED = "applied"
    SKIPPED = "skipped"
    FAILED = "failed"


class SubtitleExecution(MissionBaseModel):
    """
    One provider-independent subtitle segment.

    Timing is represented in absolute video-timeline seconds.
    Renderer-specific ASS/SRT/FFmpeg conversion happens later.
    """

    schema_version: str = "1.0"

    status: SubtitleExecutionStatus = SubtitleExecutionStatus.PLANNED

    scene_number: int = Field(
        ge=1,
    )

    segment_index: int = Field(
        ge=0,
    )

    text: str

    preset_id: str

    animation_preset_id: str | None = None

    burn_into_video: bool = True

    timing_source: SubtitleTimingSource = SubtitleTimingSource.ESTIMATED

    start_time_seconds: float = Field(
        ge=0.0,
    )

    end_time_seconds: float = Field(
        gt=0.0,
    )

    duration_seconds: float = Field(
        gt=0.0,
    )

    scene_start_time_seconds: float = Field(
        ge=0.0,
    )

    scene_end_time_seconds: float = Field(
        gt=0.0,
    )

    local_start_offset_seconds: float = Field(
        ge=0.0,
    )

    local_end_offset_seconds: float = Field(
        gt=0.0,
    )

    word_count: int = Field(
        ge=1,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    warnings: list[str] = Field(
        default_factory=list,
    )

    @field_validator(
        "text",
        "preset_id",
    )
    @classmethod
    def clean_required_text(
        cls,
        value: str,
    ) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Subtitle execution text cannot be empty.")

        return cleaned

    @field_validator("preset_id")
    @classmethod
    def validate_preset_id(
        cls,
        value: str,
    ) -> str:
        normalized = value.strip().lower()

        if not normalized.startswith("subtitle.") or normalized == "subtitle.":
            raise ValueError("Subtitle preset ID must start " "with 'subtitle.'.")

        return normalized

    @field_validator("animation_preset_id")
    @classmethod
    def validate_animation_preset_id(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        normalized = value.strip().lower()

        if not normalized.startswith("animation.") or normalized == "animation.":
            raise ValueError(
                "Subtitle animation preset ID must " "start with 'animation.'."
            )

        return normalized

    @field_validator("warnings")
    @classmethod
    def clean_warnings(
        cls,
        values: list[str],
    ) -> list[str]:
        cleaned: list[str] = []

        for value in values:
            warning = value.strip()

            if warning and warning not in cleaned:
                cleaned.append(warning)

        return cleaned

    @model_validator(mode="after")
    def validate_execution(
        self,
    ) -> SubtitleExecution:
        if self.scene_end_time_seconds <= self.scene_start_time_seconds:
            raise ValueError("Subtitle scene end must be greater " "than scene start.")

        if self.end_time_seconds <= self.start_time_seconds:
            raise ValueError("Subtitle end time must be greater " "than start time.")

        calculated_duration = self.end_time_seconds - self.start_time_seconds

        if abs(calculated_duration - self.duration_seconds) > 0.001:
            raise ValueError("Subtitle duration does not match " "execution timing.")

        if self.start_time_seconds < self.scene_start_time_seconds - 0.001:
            raise ValueError("Subtitle cannot start before its scene.")

        if self.end_time_seconds > self.scene_end_time_seconds + 0.001:
            raise ValueError("Subtitle cannot end after its scene.")

        expected_local_start = self.start_time_seconds - self.scene_start_time_seconds

        expected_local_end = self.end_time_seconds - self.scene_start_time_seconds

        if abs(expected_local_start - self.local_start_offset_seconds) > 0.001:
            raise ValueError(
                "Subtitle local start offset does not " "match global timing."
            )

        if abs(expected_local_end - self.local_end_offset_seconds) > 0.001:
            raise ValueError(
                "Subtitle local end offset does not " "match global timing."
            )

        if self.status == SubtitleExecutionStatus.APPLIED and not self.metadata.get(
            "renderer"
        ):
            raise ValueError(
                "Applied subtitle execution requires " "renderer metadata."
            )

        return self

    @property
    def is_ready(self) -> bool:
        """Return whether a renderer may consume this subtitle."""

        return self.status in {
            SubtitleExecutionStatus.VALIDATED,
            SubtitleExecutionStatus.READY,
            SubtitleExecutionStatus.APPLIED,
        }


class SubtitleExecutionPlan(MissionBaseModel):
    """Complete subtitle execution plan for a video timeline."""

    schema_version: str = "1.0"

    executions: list[SubtitleExecution] = Field(
        default_factory=list,
    )

    timeline_duration_seconds: float = Field(
        ge=0.0,
        default=0.0,
    )

    scene_count: int = Field(
        ge=0,
        default=0,
    )

    segment_count: int = Field(
        ge=0,
        default=0,
    )

    estimated_segment_count: int = Field(
        ge=0,
        default=0,
    )

    precise_segment_count: int = Field(
        ge=0,
        default=0,
    )

    ready_execution_count: int = Field(
        ge=0,
        default=0,
    )

    is_valid: bool = False

    is_render_ready: bool = False

    warnings: list[str] = Field(
        default_factory=list,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @model_validator(mode="after")
    def validate_plan(
        self,
    ) -> SubtitleExecutionPlan:
        if self.segment_count != len(self.executions):
            raise ValueError(
                "Subtitle segment count must match " "execution collection."
            )

        if self.ready_execution_count > self.segment_count:
            raise ValueError("Ready subtitle count cannot exceed " "segment count.")

        if self.is_render_ready and not self.is_valid:
            raise ValueError("Render-ready subtitle plans " "must be valid.")

        return self

    def refresh_summary(self) -> None:
        """Recalculate plan summary fields."""

        self.executions = sorted(
            self.executions,
            key=lambda execution: (
                execution.start_time_seconds,
                execution.scene_number,
                execution.segment_index,
            ),
        )

        self.segment_count = len(self.executions)

        self.estimated_segment_count = sum(
            1
            for execution in self.executions
            if (execution.timing_source == SubtitleTimingSource.ESTIMATED)
        )

        self.precise_segment_count = sum(
            1
            for execution in self.executions
            if (execution.timing_source == SubtitleTimingSource.PRECISE)
        )

        self.ready_execution_count = sum(
            1 for execution in self.executions if execution.is_ready
        )

        self.scene_count = len(
            {execution.scene_number for execution in self.executions}
        )

        self.is_valid = all(
            execution.status != SubtitleExecutionStatus.FAILED
            for execution in self.executions
        )

        self.is_render_ready = (
            self.is_valid and self.ready_execution_count == self.segment_count
        )

    @property
    def has_subtitles(self) -> bool:
        """Return whether subtitle segments exist."""

        return bool(self.executions)

    @property
    def applied_count(self) -> int:
        """Return number of applied subtitle segments."""

        return sum(
            1
            for execution in self.executions
            if (execution.status == SubtitleExecutionStatus.APPLIED)
        )

    @property
    def failed_count(self) -> int:
        """Return number of failed subtitle segments."""

        return sum(
            1
            for execution in self.executions
            if (execution.status == SubtitleExecutionStatus.FAILED)
        )
