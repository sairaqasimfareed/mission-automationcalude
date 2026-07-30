from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, field_validator, model_validator

from src.models.base import MissionBaseModel
from src.models.editing_directives import (
    DirectiveIntensity,
    DirectiveTimingMode,
)


class EffectExecutionStatus(str, Enum):
    """Lifecycle state of one visual-effect execution."""

    PLANNED = "planned"
    VALIDATED = "validated"
    READY = "ready"
    APPLIED = "applied"
    SKIPPED = "skipped"
    FAILED = "failed"


class EffectExecution(MissionBaseModel):
    """
    Provider-independent visual-effect execution instruction.

    Timing is expressed in global video-timeline seconds.
    Renderer-specific filters or commands are generated later.
    """

    schema_version: str = "1.0"

    status: EffectExecutionStatus = (
        EffectExecutionStatus.PLANNED
    )

    scene_number: int = Field(
        ge=1,
    )

    track_index: int = Field(
        default=0,
        ge=0,
    )

    layer_index: int = Field(
        default=0,
        ge=0,
    )

    preset_id: str

    effect_type: str

    timing_mode: DirectiveTimingMode

    intensity: DirectiveIntensity = (
        DirectiveIntensity.MEDIUM
    )

    start_time_seconds: float = Field(
        ge=0.0,
    )

    end_time_seconds: float = Field(
        ge=0.0,
    )

    duration_seconds: float = Field(
        gt=0.0,
    )

    scene_start_time_seconds: float = Field(
        ge=0.0,
    )

    scene_end_time_seconds: float = Field(
        ge=0.0,
    )

    scene_duration_seconds: float = Field(
        gt=0.0,
    )

    local_start_offset_seconds: float = Field(
        default=0.0,
        ge=0.0,
    )

    relative_position_percent: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
    )

    implementation: dict[str, Any] = Field(
        default_factory=dict,
    )

    warnings: list[str] = Field(
        default_factory=list,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator(
        "preset_id",
        "effect_type",
    )
    @classmethod
    def clean_required_text(
        cls,
        value: str,
    ) -> str:
        cleaned = value.strip().lower()

        if not cleaned:
            raise ValueError(
                "Effect execution text cannot be empty."
            )

        return cleaned

    @field_validator("preset_id")
    @classmethod
    def validate_preset_id(
        cls,
        value: str,
    ) -> str:
        if (
            not value.startswith("visual.")
            or value == "visual."
        ):
            raise ValueError(
                "Visual effect preset ID must start "
                "with 'visual.'."
            )

        return value

    @field_validator("warnings")
    @classmethod
    def clean_warnings(
        cls,
        values: list[str],
    ) -> list[str]:
        cleaned: list[str] = []

        for value in values:
            warning = value.strip()

            if (
                warning
                and warning not in cleaned
            ):
                cleaned.append(warning)

        return cleaned

    @model_validator(mode="after")
    def validate_execution(
        self,
    ) -> EffectExecution:
        if (
            self.scene_end_time_seconds
            <= self.scene_start_time_seconds
        ):
            raise ValueError(
                "Effect execution scene end time must "
                "be greater than scene start time."
            )

        calculated_scene_duration = (
            self.scene_end_time_seconds
            - self.scene_start_time_seconds
        )

        if (
            abs(
                calculated_scene_duration
                - self.scene_duration_seconds
            )
            > 0.001
        ):
            raise ValueError(
                "Effect execution scene duration does "
                "not match scene timing."
            )

        if (
            self.end_time_seconds
            <= self.start_time_seconds
        ):
            raise ValueError(
                "Effect execution end time must be "
                "greater than start time."
            )

        calculated_duration = (
            self.end_time_seconds
            - self.start_time_seconds
        )

        if (
            abs(
                calculated_duration
                - self.duration_seconds
            )
            > 0.001
        ):
            raise ValueError(
                "Effect execution duration does not "
                "match execution timing."
            )

        if (
            self.start_time_seconds
            < self.scene_start_time_seconds - 0.001
        ):
            raise ValueError(
                "Effect execution cannot begin before "
                "its scene."
            )

        if (
            self.end_time_seconds
            > self.scene_end_time_seconds + 0.001
        ):
            raise ValueError(
                "Effect execution cannot end after "
                "its scene."
            )

        expected_local_offset = (
            self.start_time_seconds
            - self.scene_start_time_seconds
        )

        if (
            abs(
                expected_local_offset
                - self.local_start_offset_seconds
            )
            > 0.001
        ):
            raise ValueError(
                "Effect local start offset does not "
                "match global timing."
            )

        if (
            self.timing_mode
            == DirectiveTimingMode.RELATIVE_PERCENT
            and self.relative_position_percent is None
        ):
            raise ValueError(
                "Relative-percent effect execution "
                "requires a relative position."
            )

        if (
            self.status
            == EffectExecutionStatus.APPLIED
            and not self.metadata.get("renderer")
        ):
            raise ValueError(
                "Applied visual-effect execution "
                "requires renderer metadata."
            )

        return self

    @property
    def is_ready(self) -> bool:
        """Return whether a renderer may consume this effect."""

        return self.status in {
            EffectExecutionStatus.VALIDATED,
            EffectExecutionStatus.READY,
            EffectExecutionStatus.APPLIED,
        }

    @property
    def is_full_scene(self) -> bool:
        """Return whether the effect covers the full scene."""

        return (
            self.timing_mode
            == DirectiveTimingMode.FULL_SCENE
        )

    @property
    def end_offset_seconds(self) -> float:
        """Return effect end offset relative to scene start."""

        return (
            self.end_time_seconds
            - self.scene_start_time_seconds
        )


class EffectExecutionPlan(MissionBaseModel):
    """
    Complete provider-independent visual-effect execution plan.

    The plan contains all enabled visual effects for one video
    timeline and can later be consumed by renderer adapters.
    """

    schema_version: str = "1.0"

    executions: list[
        EffectExecution
    ] = Field(
        default_factory=list,
    )

    timeline_duration_seconds: float = Field(
        default=0.0,
        ge=0.0,
    )

    scene_count: int = Field(
        default=0,
        ge=0,
    )

    effect_count: int = Field(
        default=0,
        ge=0,
    )

    full_scene_effect_count: int = Field(
        default=0,
        ge=0,
    )

    timed_effect_count: int = Field(
        default=0,
        ge=0,
    )

    ready_execution_count: int = Field(
        default=0,
        ge=0,
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
    ) -> EffectExecutionPlan:
        if self.effect_count != len(
            self.executions
        ):
            raise ValueError(
                "Effect plan count must match "
                "its execution collection."
            )

        if self.full_scene_effect_count > self.effect_count:
            raise ValueError(
                "Full-scene effect count cannot exceed "
                "total effect count."
            )

        if self.timed_effect_count > self.effect_count:
            raise ValueError(
                "Timed effect count cannot exceed "
                "total effect count."
            )

        if self.ready_execution_count > self.effect_count:
            raise ValueError(
                "Ready effect count cannot exceed "
                "total effect count."
            )

        if (
            self.is_render_ready
            and not self.is_valid
        ):
            raise ValueError(
                "Render-ready effect plans must be valid."
            )

        if (
            self.is_render_ready
            and self.ready_execution_count
            != self.effect_count
        ):
            raise ValueError(
                "Render-ready effect plans require "
                "all executions to be ready."
            )

        return self

    def refresh_summary(self) -> None:
        """Recalculate plan summary fields."""

        self.executions = sorted(
            self.executions,
            key=lambda execution: (
                execution.start_time_seconds,
                execution.track_index,
                execution.layer_index,
                execution.scene_number,
                execution.preset_id,
            ),
        )

        self.effect_count = len(
            self.executions
        )

        self.full_scene_effect_count = sum(
            1
            for execution in self.executions
            if execution.is_full_scene
        )

        self.timed_effect_count = (
            self.effect_count
            - self.full_scene_effect_count
        )

        self.ready_execution_count = sum(
            1
            for execution in self.executions
            if execution.is_ready
        )

        self.scene_count = len(
            {
                execution.scene_number
                for execution in self.executions
            }
        )

        self.is_valid = all(
            execution.status
            != EffectExecutionStatus.FAILED
            for execution in self.executions
        )

        self.is_render_ready = (
            self.is_valid
            and self.ready_execution_count
            == self.effect_count
        )

    @property
    def has_effects(self) -> bool:
        """Return whether the plan contains visual effects."""

        return bool(
            self.executions
        )

    @property
    def applied_count(self) -> int:
        """Return number of applied visual effects."""

        return sum(
            1
            for execution in self.executions
            if (
                execution.status
                == EffectExecutionStatus.APPLIED
            )
        )

    @property
    def failed_count(self) -> int:
        """Return number of failed visual effects."""

        return sum(
            1
            for execution in self.executions
            if (
                execution.status
                == EffectExecutionStatus.FAILED
            )
        )