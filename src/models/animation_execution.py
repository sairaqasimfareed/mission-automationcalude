from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, field_validator, model_validator

from src.models.base import MissionBaseModel
from src.models.editing_directives import (
    DirectiveIntensity,
)


class AnimationExecutionStatus(str, Enum):
    """Lifecycle state of one animation execution."""

    PLANNED = "planned"
    VALIDATED = "validated"
    READY = "ready"
    APPLIED = "applied"
    SKIPPED = "skipped"
    FAILED = "failed"


class AnimationExecution(MissionBaseModel):
    """
    Provider-independent animation execution.

    Timing is represented in absolute video-timeline seconds.
    Renderer-specific commands are generated later.
    """

    schema_version: str = "1.0"

    status: AnimationExecutionStatus = AnimationExecutionStatus.PLANNED

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

    animation_type: str

    target: str | None = None

    intensity: DirectiveIntensity = DirectiveIntensity.MEDIUM

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

    scene_duration_seconds: float = Field(
        gt=0.0,
    )

    local_start_offset_seconds: float = Field(
        default=0.0,
        ge=0.0,
    )

    local_end_offset_seconds: float = Field(
        gt=0.0,
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
        "animation_type",
    )
    @classmethod
    def clean_required_text(
        cls,
        value: str,
    ) -> str:
        cleaned = value.strip().lower()

        if not cleaned:
            raise ValueError("Animation execution text cannot be empty.")

        return cleaned

    @field_validator("preset_id")
    @classmethod
    def validate_preset_id(
        cls,
        value: str,
    ) -> str:
        if not value.startswith("animation.") or value == "animation.":
            raise ValueError("Animation preset ID must start " "with 'animation.'.")

        return value

    @field_validator("target")
    @classmethod
    def clean_target(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        cleaned = value.strip().lower()

        return cleaned or None

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
    ) -> AnimationExecution:
        if self.scene_end_time_seconds <= self.scene_start_time_seconds:
            raise ValueError(
                "Animation scene end time must be " "greater than scene start time."
            )

        calculated_scene_duration = (
            self.scene_end_time_seconds - self.scene_start_time_seconds
        )

        if abs(calculated_scene_duration - self.scene_duration_seconds) > 0.001:
            raise ValueError("Animation scene duration does not " "match scene timing.")

        if self.end_time_seconds <= self.start_time_seconds:
            raise ValueError("Animation end time must be greater " "than start time.")

        calculated_duration = self.end_time_seconds - self.start_time_seconds

        if abs(calculated_duration - self.duration_seconds) > 0.001:
            raise ValueError("Animation duration does not " "match execution timing.")

        if self.start_time_seconds < self.scene_start_time_seconds - 0.001:
            raise ValueError("Animation cannot start before its scene.")

        if self.end_time_seconds > self.scene_end_time_seconds + 0.001:
            raise ValueError("Animation cannot end after its scene.")

        expected_local_start = self.start_time_seconds - self.scene_start_time_seconds

        expected_local_end = self.end_time_seconds - self.scene_start_time_seconds

        if abs(expected_local_start - self.local_start_offset_seconds) > 0.001:
            raise ValueError(
                "Animation local start offset does " "not match global timing."
            )

        if abs(expected_local_end - self.local_end_offset_seconds) > 0.001:
            raise ValueError(
                "Animation local end offset does " "not match global timing."
            )

        if self.status == AnimationExecutionStatus.APPLIED and not self.metadata.get(
            "renderer"
        ):
            raise ValueError(
                "Applied animation execution requires " "renderer metadata."
            )

        return self

    @property
    def is_ready(self) -> bool:
        """Return whether renderer may consume this animation."""

        return self.status in {
            AnimationExecutionStatus.VALIDATED,
            AnimationExecutionStatus.READY,
            AnimationExecutionStatus.APPLIED,
        }

    @property
    def is_none(self) -> bool:
        """Return whether animation is effectively disabled."""

        return self.preset_id == "animation.none" or self.animation_type == "none"


class AnimationExecutionPlan(MissionBaseModel):
    """Complete animation execution plan for a video timeline."""

    schema_version: str = "1.0"

    executions: list[AnimationExecution] = Field(
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

    execution_count: int = Field(
        default=0,
        ge=0,
    )

    active_execution_count: int = Field(
        default=0,
        ge=0,
    )

    skipped_execution_count: int = Field(
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
    ) -> AnimationExecutionPlan:
        if self.execution_count != len(self.executions):
            raise ValueError(
                "Animation execution count must match " "execution collection."
            )

        if self.active_execution_count > self.execution_count:
            raise ValueError("Active animation count cannot exceed " "execution count.")

        if self.ready_execution_count > self.execution_count:
            raise ValueError("Ready animation count cannot exceed " "execution count.")

        if self.is_render_ready and not self.is_valid:
            raise ValueError("Render-ready animation plans " "must be valid.")

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

        self.execution_count = len(self.executions)

        self.active_execution_count = sum(
            1 for execution in self.executions if not execution.is_none
        )

        self.skipped_execution_count = sum(
            1
            for execution in self.executions
            if (execution.status == AnimationExecutionStatus.SKIPPED)
        )

        self.ready_execution_count = sum(
            1 for execution in self.executions if execution.is_ready
        )

        self.scene_count = len(
            {execution.scene_number for execution in self.executions}
        )

        self.is_valid = all(
            execution.status != AnimationExecutionStatus.FAILED
            for execution in self.executions
        )

        self.is_render_ready = (
            self.is_valid
            and (self.ready_execution_count + self.skipped_execution_count)
            == self.execution_count
        )

    @property
    def has_animations(self) -> bool:
        """Return whether active animations exist."""

        return any(not execution.is_none for execution in self.executions)

    @property
    def applied_count(self) -> int:
        """Return number of applied animations."""

        return sum(
            1
            for execution in self.executions
            if (execution.status == AnimationExecutionStatus.APPLIED)
        )

    @property
    def failed_count(self) -> int:
        """Return number of failed animations."""

        return sum(
            1
            for execution in self.executions
            if (execution.status == AnimationExecutionStatus.FAILED)
        )
