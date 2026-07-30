from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, field_validator, model_validator

from src.models.base import MissionBaseModel
from src.models.editing_directives import (
    DirectiveIntensity,
)


class TransitionExecutionStatus(str, Enum):
    """Lifecycle state of one transition execution."""

    PLANNED = "planned"
    VALIDATED = "validated"
    READY = "ready"
    APPLIED = "applied"
    SKIPPED = "skipped"
    FAILED = "failed"


class TransitionPlacement(str, Enum):
    """Location of a transition relative to timeline scenes."""

    TIMELINE_IN = "timeline_in"
    BETWEEN_SCENES = "between_scenes"
    TIMELINE_OUT = "timeline_out"


class TransitionDirection(str, Enum):
    """Playback direction represented by one transition."""

    IN = "in"
    OUT = "out"
    BETWEEN = "between"


class TransitionExecution(MissionBaseModel):
    """
    Provider-independent execution instruction for one transition.

    The execution contains normalized timeline timing and resolved
    transition implementation data. Renderer-specific conversion
    happens in a later adapter or command-building service.
    """

    schema_version: str = "1.0"

    status: TransitionExecutionStatus = (
        TransitionExecutionStatus.PLANNED
    )

    placement: TransitionPlacement
    direction: TransitionDirection

    preset_id: str
    transition_type: str

    source_scene_number: int | None = Field(
        default=None,
        ge=1,
    )

    target_scene_number: int | None = Field(
        default=None,
        ge=1,
    )

    source_track_index: int | None = Field(
        default=None,
        ge=0,
    )

    target_track_index: int | None = Field(
        default=None,
        ge=0,
    )

    start_time_seconds: float = Field(
        ge=0.0,
    )

    end_time_seconds: float = Field(
        ge=0.0,
    )

    duration_seconds: float = Field(
        ge=0.0,
    )

    overlap_start_seconds: float | None = Field(
        default=None,
        ge=0.0,
    )

    overlap_end_seconds: float | None = Field(
        default=None,
        ge=0.0,
    )

    intensity: DirectiveIntensity = (
        DirectiveIntensity.MEDIUM
    )

    requires_overlap: bool = False

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
        "transition_type",
    )
    @classmethod
    def clean_required_text(
        cls,
        value: str,
    ) -> str:
        cleaned = value.strip().lower()

        if not cleaned:
            raise ValueError(
                "Transition execution text "
                "cannot be empty."
            )

        return cleaned

    @field_validator("preset_id")
    @classmethod
    def validate_preset_id(
        cls,
        value: str,
    ) -> str:
        if (
            not value.startswith("transition.")
            or value == "transition."
        ):
            raise ValueError(
                "Transition preset ID must start "
                "with 'transition.'."
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
    ) -> TransitionExecution:
        actual_duration = (
            self.end_time_seconds
            - self.start_time_seconds
        )

        if self.duration_seconds == 0.0:
            if (
                abs(actual_duration) > 0.001
            ):
                raise ValueError(
                    "Zero-duration transitions require "
                    "matching start and end times."
                )
        else:
            if (
                self.end_time_seconds
                <= self.start_time_seconds
            ):
                raise ValueError(
                    "Transition end time must be greater "
                    "than start time."
                )

            if (
                abs(
                    actual_duration
                    - self.duration_seconds
                )
                > 0.001
            ):
                raise ValueError(
                    "Transition timing duration must "
                    "match duration_seconds."
                )

        if self.placement == (
            TransitionPlacement.TIMELINE_IN
        ):
            if self.direction != TransitionDirection.IN:
                raise ValueError(
                    "Timeline-in transitions require "
                    "IN direction."
                )

            if self.source_scene_number is not None:
                raise ValueError(
                    "Timeline-in transitions cannot "
                    "have a source scene."
                )

            if self.target_scene_number is None:
                raise ValueError(
                    "Timeline-in transitions require "
                    "a target scene."
                )

        elif self.placement == (
            TransitionPlacement.TIMELINE_OUT
        ):
            if self.direction != TransitionDirection.OUT:
                raise ValueError(
                    "Timeline-out transitions require "
                    "OUT direction."
                )

            if self.source_scene_number is None:
                raise ValueError(
                    "Timeline-out transitions require "
                    "a source scene."
                )

            if self.target_scene_number is not None:
                raise ValueError(
                    "Timeline-out transitions cannot "
                    "have a target scene."
                )

        elif self.placement == (
            TransitionPlacement.BETWEEN_SCENES
        ):
            if (
                self.direction
                != TransitionDirection.BETWEEN
            ):
                raise ValueError(
                    "Between-scene transitions require "
                    "BETWEEN direction."
                )

            if self.source_scene_number is None:
                raise ValueError(
                    "Between-scene transitions require "
                    "a source scene."
                )

            if self.target_scene_number is None:
                raise ValueError(
                    "Between-scene transitions require "
                    "a target scene."
                )

            if (
                self.source_scene_number
                == self.target_scene_number
            ):
                raise ValueError(
                    "A transition cannot connect a scene "
                    "to itself."
                )

        if self.requires_overlap:
            if (
                self.overlap_start_seconds is None
                or self.overlap_end_seconds is None
            ):
                raise ValueError(
                    "Overlap-based transitions require "
                    "overlap start and end times."
                )

            if (
                self.overlap_end_seconds
                <= self.overlap_start_seconds
            ):
                raise ValueError(
                    "Transition overlap end must be "
                    "greater than overlap start."
                )

            overlap_duration = (
                self.overlap_end_seconds
                - self.overlap_start_seconds
            )

            if (
                abs(
                    overlap_duration
                    - self.duration_seconds
                )
                > 0.001
            ):
                raise ValueError(
                    "Transition overlap duration must "
                    "match duration_seconds."
                )

        else:
            if (
                self.overlap_start_seconds is not None
                or self.overlap_end_seconds is not None
            ):
                raise ValueError(
                    "Non-overlap transitions cannot "
                    "contain overlap timing."
                )

        if (
            self.status
            == TransitionExecutionStatus.APPLIED
            and not self.metadata.get(
                "renderer",
            )
        ):
            raise ValueError(
                "Applied transition execution requires "
                "renderer metadata."
            )

        return self

    @property
    def is_cut(self) -> bool:
        """Return whether the transition represents a cut."""

        return (
            self.preset_id == "transition.cut"
            or self.transition_type == "cut"
        )

    @property
    def is_timed(self) -> bool:
        """Return whether the transition has duration."""

        return self.duration_seconds > 0.0

    @property
    def is_ready(self) -> bool:
        """Return whether a renderer may consume this execution."""

        return self.status in {
            TransitionExecutionStatus.VALIDATED,
            TransitionExecutionStatus.READY,
            TransitionExecutionStatus.APPLIED,
        }

    @property
    def scene_numbers(self) -> list[int]:
        """Return all scene numbers used by the execution."""

        values: list[int] = []

        if self.source_scene_number is not None:
            values.append(
                self.source_scene_number
            )

        if (
            self.target_scene_number is not None
            and self.target_scene_number
            not in values
        ):
            values.append(
                self.target_scene_number
            )

        return values


class TransitionExecutionPlan(MissionBaseModel):
    """
    Complete transition plan for one video timeline.

    Executions are ordered by playback timing and remain
    renderer-independent.
    """

    schema_version: str = "1.0"

    executions: list[
        TransitionExecution
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

    transition_count: int = Field(
        default=0,
        ge=0,
    )

    timed_transition_count: int = Field(
        default=0,
        ge=0,
    )

    cut_transition_count: int = Field(
        default=0,
        ge=0,
    )

    overlap_transition_count: int = Field(
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
    ) -> TransitionExecutionPlan:
        if self.transition_count != len(
            self.executions
        ):
            raise ValueError(
                "Transition plan count must match "
                "its execution collection."
            )

        if self.timed_transition_count > (
            self.transition_count
        ):
            raise ValueError(
                "Timed transition count cannot exceed "
                "total transition count."
            )

        if self.cut_transition_count > (
            self.transition_count
        ):
            raise ValueError(
                "Cut transition count cannot exceed "
                "total transition count."
            )

        if self.overlap_transition_count > (
            self.transition_count
        ):
            raise ValueError(
                "Overlap transition count cannot exceed "
                "total transition count."
            )

        if self.ready_execution_count > (
            self.transition_count
        ):
            raise ValueError(
                "Ready execution count cannot exceed "
                "total transition count."
            )

        if (
            self.is_render_ready
            and not self.is_valid
        ):
            raise ValueError(
                "Render-ready transition plans "
                "must be valid."
            )

        if (
            self.is_render_ready
            and self.ready_execution_count
            != self.transition_count
        ):
            raise ValueError(
                "Render-ready transition plans require "
                "all executions to be ready."
            )

        return self

    def refresh_summary(self) -> None:
        """Recalculate transition plan summary fields."""

        self.executions = sorted(
            self.executions,
            key=lambda execution: (
                execution.start_time_seconds,
                execution.end_time_seconds,
                execution.placement.value,
                execution.source_scene_number or 0,
                execution.target_scene_number or 0,
            ),
        )

        self.transition_count = len(
            self.executions
        )

        self.timed_transition_count = sum(
            1
            for execution in self.executions
            if execution.is_timed
        )

        self.cut_transition_count = sum(
            1
            for execution in self.executions
            if execution.is_cut
        )

        self.overlap_transition_count = sum(
            1
            for execution in self.executions
            if execution.requires_overlap
        )

        self.ready_execution_count = sum(
            1
            for execution in self.executions
            if execution.is_ready
        )

        scene_numbers = {
            scene_number
            for execution in self.executions
            for scene_number in execution.scene_numbers
        }

        self.scene_count = len(
            scene_numbers
        )

        self.is_valid = all(
            execution.status
            != TransitionExecutionStatus.FAILED
            for execution in self.executions
        )

        self.is_render_ready = (
            self.is_valid
            and self.ready_execution_count
            == self.transition_count
        )

    @property
    def has_transitions(self) -> bool:
        """Return whether any transitions are planned."""

        return bool(
            self.executions
        )

    @property
    def applied_count(self) -> int:
        """Return the number of applied transitions."""

        return sum(
            1
            for execution in self.executions
            if (
                execution.status
                == TransitionExecutionStatus.APPLIED
            )
        )

    @property
    def failed_count(self) -> int:
        """Return the number of failed transitions."""

        return sum(
            1
            for execution in self.executions
            if (
                execution.status
                == TransitionExecutionStatus.FAILED
            )
        )