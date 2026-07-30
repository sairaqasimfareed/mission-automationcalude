from __future__ import annotations

from typing import Any

from src.models.camera_execution import (
    CameraExecution,
    CameraExecutionPlan,
    CameraExecutionStatus,
)
from src.models.resolved_editing_blueprint import (
    ResolvedCameraInstruction,
)
from src.models.video_timeline import VideoTimeline
from src.models.video_timeline_item import (
    VideoTimelineItem,
)
from src.services.timeline_validation_service import (
    TimelineValidationService,
)


class CameraExecutionService:
    """
    Build provider-independent camera-motion execution plans.

    Resolved camera instructions are converted from scene-local
    timing to absolute video-timeline timing. Renderer-specific
    FFmpeg or other commands are generated later.
    """

    TIME_TOLERANCE_SECONDS = 0.001

    def __init__(
        self,
        *,
        timeline_validation_service: (
            TimelineValidationService | None
        ) = None,
    ) -> None:
        self.timeline_validation_service = (
            timeline_validation_service
            or TimelineValidationService()
        )

    def build_plan(
        self,
        timeline: VideoTimeline,
        *,
        track_index: int | None = None,
        validate_timeline: bool = True,
        include_static: bool = True,
        mark_ready: bool = True,
    ) -> CameraExecutionPlan:
        """Build camera executions for enabled timeline scenes."""

        if (
            track_index is not None
            and track_index < 0
        ):
            raise ValueError(
                "Camera plan track index "
                "cannot be negative."
            )

        if validate_timeline:
            validation_result = (
                self.timeline_validation_service.validate(
                    timeline,
                    require_gap_free_primary_track=True,
                    require_editing_blueprints=True,
                    warn_on_blueprint_fallbacks=True,
                )
            )

            if not validation_result.is_valid:
                raise ValueError(
                    "Video timeline is not valid for "
                    "camera execution planning. "
                    + " ".join(
                        issue.message
                        for issue
                        in validation_result.errors
                    )
                )

        items = [
            item
            for item in timeline.ordered_items()
            if (
                track_index is None
                or item.track_index == track_index
            )
        ]

        if not items:
            raise ValueError(
                "Camera execution planning requires "
                "at least one enabled timeline item."
            )

        executions: list[
            CameraExecution
        ] = []

        warnings: list[str] = []

        for item in items:
            execution = self.build_execution(
                item=item,
            )

            if (
                execution.is_static
                and not include_static
            ):
                continue

            executions.append(
                execution
            )

            warnings.extend(
                execution.warnings
            )

        plan = self._create_plan(
            timeline=timeline,
            executions=executions,
            warnings=warnings,
            metadata={
                "track_index": track_index,
                "include_static": include_static,
                "timeline_validation_performed": (
                    validate_timeline
                ),
            },
        )

        self.validate_plan(
            plan
        )

        if mark_ready:
            self.mark_ready(
                plan
            )

        return plan

    def build_execution(
        self,
        *,
        item: VideoTimelineItem,
    ) -> CameraExecution:
        """Build one normalized camera execution."""

        blueprint = item.editing_blueprint

        if blueprint is None:
            raise ValueError(
                "Camera execution planning requires "
                "an editing blueprint."
            )

        if not blueprint.is_resolved:
            raise ValueError(
                "Camera execution planning requires "
                "a resolved editing blueprint."
            )

        if (
            blueprint.scene_number
            != item.scene_number
        ):
            raise ValueError(
                "Editing blueprint scene number "
                "does not match timeline item."
            )

        instruction = blueprint.camera

        return self._build_from_instruction(
            item=item,
            instruction=instruction,
        )

    def validate_plan(
        self,
        plan: CameraExecutionPlan,
    ) -> CameraExecutionPlan:
        """Validate all camera executions."""

        errors: list[str] = []

        for execution in plan.executions:
            execution_errors = (
                self._execution_errors(
                    execution=execution,
                    timeline_duration_seconds=(
                        plan.timeline_duration_seconds
                    ),
                )
            )

            if execution_errors:
                execution.status = (
                    CameraExecutionStatus.FAILED
                )

                for message in execution_errors:
                    if (
                        message
                        not in execution.warnings
                    ):
                        execution.warnings.append(
                            message
                        )

                    errors.append(
                        message
                    )

            elif (
                execution.status
                == CameraExecutionStatus.PLANNED
            ):
                execution.status = (
                    CameraExecutionStatus.VALIDATED
                )

        plan.warnings = self._unique_text(
            [
                *plan.warnings,
                *[
                    warning
                    for execution
                    in plan.executions
                    for warning
                    in execution.warnings
                ],
            ]
        )

        plan.metadata[
            "validation_errors"
        ] = self._unique_text(
            errors
        )

        plan.refresh_summary()

        plan.is_valid = (
            len(errors) == 0
            and plan.failed_count == 0
        )

        plan.is_render_ready = (
            plan.is_valid
            and plan.ready_execution_count
            == plan.execution_count
        )

        return plan

    def mark_ready(
        self,
        plan: CameraExecutionPlan,
    ) -> CameraExecutionPlan:
        """Mark validated camera executions as ready."""

        self.validate_plan(
            plan
        )

        if not plan.is_valid:
            raise ValueError(
                "Invalid camera execution plan "
                "cannot be marked ready."
            )

        for execution in plan.executions:
            if (
                execution.status
                == CameraExecutionStatus.VALIDATED
            ):
                execution.status = (
                    CameraExecutionStatus.READY
                )

        plan.refresh_summary()

        return plan

    def mark_applied(
        self,
        plan: CameraExecutionPlan,
        *,
        execution_id: str,
        renderer: str,
        renderer_metadata: (
            dict[str, Any] | None
        ) = None,
    ) -> CameraExecution:
        """Mark one ready camera execution as applied."""

        cleaned_renderer = (
            renderer.strip()
        )

        if not cleaned_renderer:
            raise ValueError(
                "Applied camera execution requires "
                "a renderer name."
            )

        execution = self._find_execution(
            plan=plan,
            execution_id=execution_id,
        )

        if execution.status not in {
            CameraExecutionStatus.READY,
            CameraExecutionStatus.APPLIED,
        }:
            raise ValueError(
                "Only ready camera executions "
                "can be marked applied."
            )

        execution.metadata[
            "renderer"
        ] = cleaned_renderer

        execution.metadata[
            "renderer_metadata"
        ] = dict(
            renderer_metadata or {}
        )

        execution.status = (
            CameraExecutionStatus.APPLIED
        )

        plan.refresh_summary()

        return execution

    def mark_all_applied(
        self,
        plan: CameraExecutionPlan,
        *,
        renderer: str,
        renderer_metadata: (
            dict[str, Any] | None
        ) = None,
    ) -> list[CameraExecution]:
        """Mark every ready camera execution as applied."""

        cleaned_renderer = (
            renderer.strip()
        )

        if not cleaned_renderer:
            raise ValueError(
                "Applied camera executions require "
                "a renderer name."
            )

        if not plan.is_render_ready:
            raise ValueError(
                "Camera execution plan must be "
                "render-ready before application."
            )

        applied: list[
            CameraExecution
        ] = []

        for execution in plan.executions:
            applied.append(
                self.mark_applied(
                    plan,
                    execution_id=str(
                        execution.id
                    ),
                    renderer=cleaned_renderer,
                    renderer_metadata=(
                        renderer_metadata
                    ),
                )
            )

        return applied

    def mark_failed(
        self,
        plan: CameraExecutionPlan,
        *,
        execution_id: str,
        error_message: str,
        failure_metadata: (
            dict[str, Any] | None
        ) = None,
    ) -> CameraExecution:
        """Mark one camera execution as failed."""

        cleaned_message = (
            error_message.strip()
        )

        if not cleaned_message:
            raise ValueError(
                "Camera execution failure message "
                "cannot be empty."
            )

        execution = self._find_execution(
            plan=plan,
            execution_id=execution_id,
        )

        execution.status = (
            CameraExecutionStatus.FAILED
        )

        execution.metadata[
            "failure_message"
        ] = cleaned_message

        execution.metadata[
            "failure_details"
        ] = dict(
            failure_metadata or {}
        )

        warning = (
            "Camera execution failed: "
            f"{cleaned_message}"
        )

        if warning not in execution.warnings:
            execution.warnings.append(
                warning
            )

        plan.warnings = self._unique_text(
            [
                *plan.warnings,
                warning,
            ]
        )

        plan.refresh_summary()

        plan.is_valid = False
        plan.is_render_ready = False

        return execution

    def summary(
        self,
        plan: CameraExecutionPlan,
    ) -> dict[str, Any]:
        """Return serializable camera-plan summary."""

        plan.refresh_summary()

        return {
            "plan_id": str(plan.id),
            "schema_version": (
                plan.schema_version
            ),
            "timeline_duration_seconds": (
                plan.timeline_duration_seconds
            ),
            "scene_count": (
                plan.scene_count
            ),
            "execution_count": (
                plan.execution_count
            ),
            "static_execution_count": (
                plan.static_execution_count
            ),
            "motion_execution_count": (
                plan.motion_execution_count
            ),
            "ready_execution_count": (
                plan.ready_execution_count
            ),
            "applied_count": (
                plan.applied_count
            ),
            "failed_count": (
                plan.failed_count
            ),
            "is_valid": (
                plan.is_valid
            ),
            "is_render_ready": (
                plan.is_render_ready
            ),
            "warnings": list(
                plan.warnings
            ),
            "metadata": dict(
                plan.metadata
            ),
        }

    def _build_from_instruction(
        self,
        *,
        item: VideoTimelineItem,
        instruction: ResolvedCameraInstruction,
    ) -> CameraExecution:
        """Convert one resolved camera instruction."""

        preset = instruction.preset

        preset_id = (
            preset.resolved_preset_id
        )

        if not preset_id.startswith(
            "camera."
        ):
            raise ValueError(
                "Camera execution requires "
                "a camera preset."
            )

        implementation = dict(
            preset.implementation
        )

        motion_type = (
            self._motion_type(
                preset_id=preset_id,
                implementation=implementation,
            )
        )

        direction = (
            self._optional_text(
                implementation.get(
                    "direction"
                )
            )
        )

        scene_duration = (
            item.duration_seconds
        )

        local_start = float(
            instruction.start_offset_seconds
        )

        if (
            local_start
            >= scene_duration
        ):
            raise ValueError(
                "Camera start offset must occur "
                "before scene end."
            )

        local_end = (
            float(
                instruction.end_offset_seconds
            )
            if (
                instruction.end_offset_seconds
                is not None
            )
            else scene_duration
        )

        if (
            local_end
            <= local_start
        ):
            raise ValueError(
                "Camera end offset must be greater "
                "than start offset."
            )

        if (
            local_end
            > scene_duration
            + self.TIME_TOLERANCE_SECONDS
        ):
            raise ValueError(
                "Camera execution extends "
                "beyond scene duration."
            )

        duration = (
            local_end - local_start
        )

        zoom_start = (
            instruction.zoom_start
        )

        zoom_end = (
            instruction.zoom_end
        )

        if motion_type == "zoom":
            if zoom_start is None:
                zoom_start = (
                    self._optional_float(
                        implementation.get(
                            "default_start_scale"
                        )
                    )
                )

            if zoom_end is None:
                zoom_end = (
                    self._optional_float(
                        implementation.get(
                            "default_end_scale"
                        )
                    )
                )

            if (
                zoom_start is None
                or zoom_end is None
            ):
                raise ValueError(
                    "Zoom camera preset requires "
                    "start and end scales."
                )

        warnings: list[str] = []

        if preset.used_fallback:
            warnings.append(
                "Camera execution uses "
                "a fallback preset."
            )

        return CameraExecution(
            status=CameraExecutionStatus.PLANNED,
            scene_number=item.scene_number,
            track_index=item.track_index,
            layer_index=item.layer_index,
            preset_id=preset_id,
            motion_type=motion_type,
            direction=direction,
            intensity=instruction.intensity,
            start_time_seconds=(
                item.start_time_seconds
                + local_start
            ),
            end_time_seconds=(
                item.start_time_seconds
                + local_end
            ),
            duration_seconds=duration,
            scene_start_time_seconds=(
                item.start_time_seconds
            ),
            scene_end_time_seconds=(
                item.end_time_seconds
            ),
            scene_duration_seconds=(
                scene_duration
            ),
            local_start_offset_seconds=(
                local_start
            ),
            local_end_offset_seconds=(
                local_end
            ),
            zoom_start=zoom_start,
            zoom_end=zoom_end,
            implementation=implementation,
            warnings=warnings,
            metadata={
                "timeline_item_id": str(
                    item.id
                ),
                "directive_path": (
                    preset.directive_path
                ),
                "found_exact_match": (
                    preset.found_exact_match
                ),
                "used_fallback": (
                    preset.used_fallback
                ),
            },
        )

    @staticmethod
    def _motion_type(
        *,
        preset_id: str,
        implementation: dict[str, Any],
    ) -> str:
        """Resolve normalized camera motion type."""

        motion = implementation.get(
            "motion"
        )

        if isinstance(
            motion,
            str,
        ):
            cleaned = (
                motion.strip().lower()
            )

            if cleaned:
                return cleaned

        if preset_id == "camera.none":
            return "none"

        return (
            preset_id
            .split(
                ".",
                maxsplit=1,
            )[-1]
            .strip()
            .lower()
        )

    @staticmethod
    def _optional_text(
        value: Any,
    ) -> str | None:
        if not isinstance(
            value,
            str,
        ):
            return None

        cleaned = (
            value.strip().lower()
        )

        return cleaned or None

    @staticmethod
    def _optional_float(
        value: Any,
    ) -> float | None:
        if isinstance(
            value,
            bool,
        ):
            return None

        if isinstance(
            value,
            (int, float),
        ):
            return float(
                value
            )

        return None

    @staticmethod
    def _execution_errors(
        *,
        execution: CameraExecution,
        timeline_duration_seconds: float,
    ) -> list[str]:
        """Return validation errors for one camera execution."""

        errors: list[str] = []

        if (
            execution.start_time_seconds
            < execution.scene_start_time_seconds
            - 0.001
        ):
            errors.append(
                "Camera execution begins "
                "before its scene."
            )

        if (
            execution.end_time_seconds
            > execution.scene_end_time_seconds
            + 0.001
        ):
            errors.append(
                "Camera execution ends "
                "after its scene."
            )

        if (
            execution.end_time_seconds
            > timeline_duration_seconds
            + 0.001
        ):
            errors.append(
                "Camera execution ends "
                "after video timeline."
            )

        if (
            execution.is_zoom
            and (
                execution.zoom_start is None
                or execution.zoom_end is None
            )
        ):
            errors.append(
                "Zoom camera execution lacks "
                "zoom scale values."
            )

        return errors

    @staticmethod
    def _create_plan(
        *,
        timeline: VideoTimeline,
        executions: list[
            CameraExecution
        ],
        warnings: list[str],
        metadata: dict[str, Any],
    ) -> CameraExecutionPlan:
        """Create initial model-valid camera plan."""

        ordered = sorted(
            executions,
            key=lambda execution: (
                execution.start_time_seconds,
                execution.track_index,
                execution.layer_index,
                execution.scene_number,
            ),
        )

        execution_count = len(
            ordered
        )

        static_count = sum(
            1
            for execution in ordered
            if execution.is_static
        )

        ready_count = sum(
            1
            for execution in ordered
            if execution.is_ready
        )

        return CameraExecutionPlan(
            executions=ordered,
            timeline_duration_seconds=(
                timeline.calculate_duration()
            ),
            scene_count=len(
                {
                    execution.scene_number
                    for execution in ordered
                }
            ),
            execution_count=(
                execution_count
            ),
            static_execution_count=(
                static_count
            ),
            motion_execution_count=(
                execution_count - static_count
            ),
            ready_execution_count=(
                ready_count
            ),
            is_valid=True,
            is_render_ready=(
                ready_count
                == execution_count
            ),
            warnings=(
                CameraExecutionService
                ._unique_text(
                    warnings
                )
            ),
            metadata=dict(
                metadata
            ),
        )

    @staticmethod
    def _find_execution(
        *,
        plan: CameraExecutionPlan,
        execution_id: str,
    ) -> CameraExecution:
        """Return one camera execution by ID."""

        cleaned = (
            execution_id.strip()
        )

        if not cleaned:
            raise ValueError(
                "Camera execution ID "
                "cannot be empty."
            )

        matches = [
            execution
            for execution in plan.executions
            if str(execution.id) == cleaned
        ]

        if not matches:
            raise KeyError(
                "Camera execution was not found: "
                f"{cleaned}"
            )

        if len(matches) > 1:
            raise ValueError(
                "Multiple camera executions "
                "share the same ID."
            )

        return matches[0]

    @staticmethod
    def _unique_text(
        values: list[str],
    ) -> list[str]:
        """Return normalized unique text."""

        cleaned: list[str] = []

        for value in values:
            normalized = (
                value.strip()
            )

            if (
                normalized
                and normalized not in cleaned
            ):
                cleaned.append(
                    normalized
                )

        return cleaned