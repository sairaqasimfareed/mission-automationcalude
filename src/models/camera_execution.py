from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, field_validator, model_validator

from src.models.base import MissionBaseModel
from src.models.editing_directives import (
    DirectiveIntensity,
)


class CameraExecutionStatus(str, Enum):
    """Lifecycle state of one camera execution."""

    PLANNED = "planned"
    VALIDATED = "validated"
    READY = "ready"
    APPLIED = "applied"
    SKIPPED = "skipped"
    FAILED = "failed"


class CameraExecution(MissionBaseModel):
    """
    Provider-independent camera-motion execution.

    Timing is expressed in absolute video-timeline seconds.
    Renderer-specific filters are generated later.
    """

    schema_version: str = "1.0"

    status: CameraExecutionStatus = CameraExecutionStatus.PLANNED

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

    motion_type: str

    direction: str | None = None

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

    zoom_start: float | None = Field(
        default=None,
        gt=0.0,
    )

    zoom_end: float | None = Field(
        default=None,
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
        "motion_type",
    )
    @classmethod
    def clean_required_text(
        cls,
        value: str,
    ) -> str:
        cleaned = value.strip().lower()

        if not cleaned:
            raise ValueError("Camera execution text cannot be empty.")

        return cleaned

    @field_validator("preset_id")
    @classmethod
    def validate_preset_id(
        cls,
        value: str,
    ) -> str:
        if not value.startswith("camera.") or value == "camera.":
            raise ValueError("Camera preset ID must start " "with 'camera.'.")

        return value

    @field_validator("direction")
    @classmethod
    def clean_direction(
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
    ) -> CameraExecution:
        if self.scene_end_time_seconds <= self.scene_start_time_seconds:
            raise ValueError(
                "Camera scene end time must be greater " "than scene start time."
            )

        calculated_scene_duration = (
            self.scene_end_time_seconds - self.scene_start_time_seconds
        )

        if abs(calculated_scene_duration - self.scene_duration_seconds) > 0.001:
            raise ValueError("Camera scene duration does not " "match scene timing.")

        if self.end_time_seconds <= self.start_time_seconds:
            raise ValueError(
                "Camera execution end time must be " "greater than start time."
            )

        calculated_duration = self.end_time_seconds - self.start_time_seconds

        if abs(calculated_duration - self.duration_seconds) > 0.001:
            raise ValueError("Camera execution duration does not " "match timing.")

        if self.start_time_seconds < self.scene_start_time_seconds - 0.001:
            raise ValueError("Camera execution cannot begin " "before its scene.")

        if self.end_time_seconds > self.scene_end_time_seconds + 0.001:
            raise ValueError("Camera execution cannot end " "after its scene.")

        expected_local_start = self.start_time_seconds - self.scene_start_time_seconds

        expected_local_end = self.end_time_seconds - self.scene_start_time_seconds

        if abs(expected_local_start - self.local_start_offset_seconds) > 0.001:
            raise ValueError(
                "Camera local start offset does not " "match global timing."
            )

        if abs(expected_local_end - self.local_end_offset_seconds) > 0.001:
            raise ValueError("Camera local end offset does not " "match global timing.")

        if self.motion_type == "zoom" and (
            self.zoom_start is None or self.zoom_end is None
        ):
            raise ValueError(
                "Zoom camera executions require " "zoom_start and zoom_end."
            )

        if self.status == CameraExecutionStatus.APPLIED and not self.metadata.get(
            "renderer"
        ):
            raise ValueError("Applied camera execution requires " "renderer metadata.")

        return self

    @property
    def is_ready(self) -> bool:
        """Return whether a renderer may consume this execution."""

        return self.status in {
            CameraExecutionStatus.VALIDATED,
            CameraExecutionStatus.READY,
            CameraExecutionStatus.APPLIED,
        }

    @property
    def is_static(self) -> bool:
        """Return whether camera motion is disabled."""

        return self.preset_id == "camera.none" or self.motion_type == "none"

    @property
    def is_zoom(self) -> bool:
        """Return whether the execution represents zoom motion."""

        return self.motion_type == "zoom"


class CameraExecutionPlan(MissionBaseModel):
    """Complete camera execution plan for one video timeline."""

    schema_version: str = "1.0"

    executions: list[CameraExecution] = Field(
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

    static_execution_count: int = Field(
        default=0,
        ge=0,
    )

    motion_execution_count: int = Field(
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
    ) -> CameraExecutionPlan:
        if self.execution_count != len(self.executions):
            raise ValueError(
                "Camera execution count must match " "execution collection."
            )

        if self.static_execution_count > self.execution_count:
            raise ValueError("Static camera count cannot exceed " "execution count.")

        if self.motion_execution_count > self.execution_count:
            raise ValueError("Motion camera count cannot exceed " "execution count.")

        if self.ready_execution_count > self.execution_count:
            raise ValueError("Ready camera count cannot exceed " "execution count.")

        if self.is_render_ready and not self.is_valid:
            raise ValueError("Render-ready camera plans " "must be valid.")

        return self

    def refresh_summary(self) -> None:
        """Recalculate camera plan summary fields."""

        self.executions = sorted(
            self.executions,
            key=lambda execution: (
                execution.start_time_seconds,
                execution.track_index,
                execution.layer_index,
                execution.scene_number,
            ),
        )

        self.execution_count = len(self.executions)

        self.static_execution_count = sum(
            1 for execution in self.executions if execution.is_static
        )

        self.motion_execution_count = self.execution_count - self.static_execution_count

        self.ready_execution_count = sum(
            1 for execution in self.executions if execution.is_ready
        )

        self.scene_count = len(
            {execution.scene_number for execution in self.executions}
        )

        self.is_valid = all(
            execution.status != CameraExecutionStatus.FAILED
            for execution in self.executions
        )

        self.is_render_ready = (
            self.is_valid and self.ready_execution_count == self.execution_count
        )

    @property
    def has_executions(self) -> bool:
        """Return whether camera executions exist."""

        return bool(self.executions)

    @property
    def applied_count(self) -> int:
        """Return number of applied camera executions."""

        return sum(
            1
            for execution in self.executions
            if (execution.status == CameraExecutionStatus.APPLIED)
        )

    @property
    def failed_count(self) -> int:
        """Return number of failed camera executions."""

        return sum(
            1
            for execution in self.executions
            if (execution.status == CameraExecutionStatus.FAILED)
        )
