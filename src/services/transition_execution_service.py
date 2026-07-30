from __future__ import annotations

from typing import Any

from src.models.resolved_editing_blueprint import (
    ResolvedTransitionInstruction,
)
from src.models.transition_execution import (
    TransitionDirection,
    TransitionExecution,
    TransitionExecutionPlan,
    TransitionExecutionStatus,
    TransitionPlacement,
)
from src.models.video_timeline import VideoTimeline
from src.models.video_timeline_item import (
    VideoTimelineItem,
)
from src.services.timeline_validation_service import (
    TimelineValidationService,
)


class TransitionExecutionService:
    """
    Build provider-independent transition execution plans.

    The service converts resolved scene transition instructions
    attached to a VideoTimeline into normalized, renderer-ready
    transition executions.

    It does not execute FFmpeg commands or render video.
    """

    TIME_TOLERANCE_SECONDS = 0.001

    OVERLAP_TRANSITION_TYPES = {
        "cross_dissolve",
        "dissolve",
        "xfade",
        "wipe",
        "slide",
        "push",
    }

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
        track_index: int = 0,
        include_timeline_in: bool = True,
        include_timeline_out: bool = True,
        validate_timeline: bool = True,
        mark_ready: bool = True,
    ) -> TransitionExecutionPlan:
        """
        Build a transition execution plan for one video track.

        One transition execution is created for:

        - The beginning of the timeline, when enabled.
        - Every boundary between consecutive scenes.
        - The end of the timeline, when enabled.

        Between-scene transition conflicts are resolved using a
        deterministic selection policy.
        """

        if track_index < 0:
            raise ValueError(
                "Transition plan track index "
                "cannot be negative."
            )

        if validate_timeline:
            validation_result = (
                self.timeline_validation_service.validate(
                    timeline,
                    require_gap_free_primary_track=(
                        track_index == 0
                    ),
                    require_editing_blueprints=True,
                    warn_on_blueprint_fallbacks=True,
                )
            )

            if not validation_result.is_valid:
                messages = [
                    issue.message
                    for issue in validation_result.errors
                ]

                raise ValueError(
                    "Video timeline is not valid for "
                    "transition planning. "
                    + " ".join(messages)
                )

        items = self._track_items(
            timeline=timeline,
            track_index=track_index,
        )

        if not items:
            raise ValueError(
                "Transition execution planning requires "
                "at least one enabled timeline item."
            )

        self._validate_items(
            items
        )

        executions: list[
            TransitionExecution
        ] = []

        plan_warnings: list[str] = []

        if include_timeline_in:
            executions.append(
                self.build_timeline_in(
                    item=items[0],
                )
            )

        for source_item, target_item in zip(
            items,
            items[1:],
        ):
            execution = self.build_between_scenes(
                source_item=source_item,
                target_item=target_item,
            )

            executions.append(
                execution
            )

            plan_warnings.extend(
                execution.warnings
            )

        if include_timeline_out:
            executions.append(
                self.build_timeline_out(
                    item=items[-1],
                )
            )

        plan = self._create_plan(
            executions=executions,
            timeline=timeline,
            scene_count=len(
                {
                    item.scene_number
                    for item in items
                }
            ),
            warnings=plan_warnings,
            metadata={
                "track_index": track_index,
                "include_timeline_in": (
                    include_timeline_in
                ),
                "include_timeline_out": (
                    include_timeline_out
                ),
                "timeline_validation_performed": (
                    validate_timeline
                ),
            },
        )

        self.validate_plan(
            plan,
        )

        if mark_ready:
            self.mark_ready(
                plan
            )

        return plan

    def build_timeline_in(
        self,
        *,
        item: VideoTimelineItem,
    ) -> TransitionExecution:
        """Build the transition entering the first scene."""

        blueprint = self._require_blueprint(
            item
        )

        instruction = (
            blueprint.transition_in
        )

        preset_id = (
            instruction
            .preset
            .resolved_preset_id
        )

        transition_type = (
            self._transition_type(
                instruction
            )
        )

        duration = self._normalized_duration(
            instruction=instruction,
            maximum_duration=(
                item.duration_seconds
            ),
            context=(
                "timeline-in transition"
            ),
        )

        start_time = (
            item.start_time_seconds
        )

        end_time = (
            start_time + duration
        )

        warnings = self._instruction_warnings(
            instruction=instruction,
            context="timeline-in",
        )

        return TransitionExecution(
            status=(
                TransitionExecutionStatus
                .PLANNED
            ),
            placement=(
                TransitionPlacement.TIMELINE_IN
            ),
            direction=TransitionDirection.IN,
            preset_id=preset_id,
            transition_type=transition_type,
            source_scene_number=None,
            target_scene_number=(
                item.scene_number
            ),
            source_track_index=None,
            target_track_index=(
                item.track_index
            ),
            start_time_seconds=(
                start_time
            ),
            end_time_seconds=end_time,
            duration_seconds=duration,
            overlap_start_seconds=None,
            overlap_end_seconds=None,
            intensity=instruction.intensity,
            requires_overlap=False,
            implementation=dict(
                instruction
                .preset
                .implementation
            ),
            warnings=warnings,
            metadata={
                "timeline_item_id": str(
                    item.id
                ),
                "target_layer_index": (
                    item.layer_index
                ),
                "source_directive_path": (
                    instruction
                    .preset
                    .directive_path
                ),
                "found_exact_match": (
                    instruction
                    .preset
                    .found_exact_match
                ),
                "used_fallback": (
                    instruction
                    .preset
                    .used_fallback
                ),
            },
        )

    def build_between_scenes(
        self,
        *,
        source_item: VideoTimelineItem,
        target_item: VideoTimelineItem,
    ) -> TransitionExecution:
        """Build one transition between consecutive scenes."""

        if (
            source_item.track_index
            != target_item.track_index
        ):
            raise ValueError(
                "Between-scene transitions require "
                "items on the same video track."
            )

        if (
            source_item.scene_number
            == target_item.scene_number
        ):
            raise ValueError(
                "A transition cannot connect a scene "
                "to itself."
            )

        boundary_difference = (
            target_item.start_time_seconds
            - source_item.end_time_seconds
        )

        if (
            abs(boundary_difference)
            > self.TIME_TOLERANCE_SECONDS
        ):
            raise ValueError(
                "Between-scene transition planning "
                "requires contiguous timeline items."
            )

        source_blueprint = (
            self._require_blueprint(
                source_item
            )
        )

        target_blueprint = (
            self._require_blueprint(
                target_item
            )
        )

        source_instruction = (
            source_blueprint.transition_out
        )

        target_instruction = (
            target_blueprint.transition_in
        )

        selected_instruction, warnings = (
            self._select_boundary_instruction(
                source_instruction=(
                    source_instruction
                ),
                target_instruction=(
                    target_instruction
                ),
                source_scene_number=(
                    source_item.scene_number
                ),
                target_scene_number=(
                    target_item.scene_number
                ),
            )
        )

        preset_id = (
            selected_instruction
            .preset
            .resolved_preset_id
        )

        transition_type = (
            self._transition_type(
                selected_instruction
            )
        )

        requires_overlap = (
            self._requires_overlap(
                instruction=(
                    selected_instruction
                ),
                transition_type=(
                    transition_type
                ),
            )
        )

        maximum_duration = self._maximum_between_duration(
            source_item=source_item,
            target_item=target_item,
            requires_overlap=(
                requires_overlap
            ),
        )

        duration = self._normalized_duration(
            instruction=(
                selected_instruction
            ),
            maximum_duration=(
                maximum_duration
            ),
            context=(
                "between-scene transition"
            ),
        )

        boundary_time = (
            source_item.end_time_seconds
        )

        (
            start_time,
            end_time,
            overlap_start,
            overlap_end,
        ) = self._between_timing(
            boundary_time=boundary_time,
            duration_seconds=duration,
            source_item=source_item,
            target_item=target_item,
            requires_overlap=(
                requires_overlap
            ),
        )

        warnings.extend(
            self._instruction_warnings(
                instruction=(
                    selected_instruction
                ),
                context=(
                    "between-scene"
                ),
            )
        )

        return TransitionExecution(
            status=(
                TransitionExecutionStatus
                .PLANNED
            ),
            placement=(
                TransitionPlacement
                .BETWEEN_SCENES
            ),
            direction=(
                TransitionDirection.BETWEEN
            ),
            preset_id=preset_id,
            transition_type=transition_type,
            source_scene_number=(
                source_item.scene_number
            ),
            target_scene_number=(
                target_item.scene_number
            ),
            source_track_index=(
                source_item.track_index
            ),
            target_track_index=(
                target_item.track_index
            ),
            start_time_seconds=start_time,
            end_time_seconds=end_time,
            duration_seconds=duration,
            overlap_start_seconds=(
                overlap_start
            ),
            overlap_end_seconds=(
                overlap_end
            ),
            intensity=(
                selected_instruction.intensity
            ),
            requires_overlap=(
                requires_overlap
            ),
            implementation=dict(
                selected_instruction
                .preset
                .implementation
            ),
            warnings=warnings,
            metadata={
                "boundary_time_seconds": (
                    boundary_time
                ),
                "source_timeline_item_id": str(
                    source_item.id
                ),
                "target_timeline_item_id": str(
                    target_item.id
                ),
                "source_layer_index": (
                    source_item.layer_index
                ),
                "target_layer_index": (
                    target_item.layer_index
                ),
                "source_transition_out_id": (
                    source_instruction
                    .preset
                    .resolved_preset_id
                ),
                "target_transition_in_id": (
                    target_instruction
                    .preset
                    .resolved_preset_id
                ),
                "source_directive_path": (
                    selected_instruction
                    .preset
                    .directive_path
                ),
                "found_exact_match": (
                    selected_instruction
                    .preset
                    .found_exact_match
                ),
                "used_fallback": (
                    selected_instruction
                    .preset
                    .used_fallback
                ),
            },
        )

    def build_timeline_out(
        self,
        *,
        item: VideoTimelineItem,
    ) -> TransitionExecution:
        """Build the transition leaving the final scene."""

        blueprint = self._require_blueprint(
            item
        )

        instruction = (
            blueprint.transition_out
        )

        preset_id = (
            instruction
            .preset
            .resolved_preset_id
        )

        transition_type = (
            self._transition_type(
                instruction
            )
        )

        duration = self._normalized_duration(
            instruction=instruction,
            maximum_duration=(
                item.duration_seconds
            ),
            context=(
                "timeline-out transition"
            ),
        )

        end_time = (
            item.end_time_seconds
        )

        start_time = (
            end_time - duration
        )

        warnings = self._instruction_warnings(
            instruction=instruction,
            context="timeline-out",
        )

        return TransitionExecution(
            status=(
                TransitionExecutionStatus
                .PLANNED
            ),
            placement=(
                TransitionPlacement.TIMELINE_OUT
            ),
            direction=TransitionDirection.OUT,
            preset_id=preset_id,
            transition_type=transition_type,
            source_scene_number=(
                item.scene_number
            ),
            target_scene_number=None,
            source_track_index=(
                item.track_index
            ),
            target_track_index=None,
            start_time_seconds=(
                start_time
            ),
            end_time_seconds=end_time,
            duration_seconds=duration,
            overlap_start_seconds=None,
            overlap_end_seconds=None,
            intensity=instruction.intensity,
            requires_overlap=False,
            implementation=dict(
                instruction
                .preset
                .implementation
            ),
            warnings=warnings,
            metadata={
                "timeline_item_id": str(
                    item.id
                ),
                "source_layer_index": (
                    item.layer_index
                ),
                "source_directive_path": (
                    instruction
                    .preset
                    .directive_path
                ),
                "found_exact_match": (
                    instruction
                    .preset
                    .found_exact_match
                ),
                "used_fallback": (
                    instruction
                    .preset
                    .used_fallback
                ),
            },
        )

    def validate_plan(
        self,
        plan: TransitionExecutionPlan,
    ) -> TransitionExecutionPlan:
        """
        Validate all transition executions in one plan.

        Valid executions move from PLANNED to VALIDATED.
        Failed executions prevent plan validity.
        """

        errors: list[str] = []

        previous_execution: (
            TransitionExecution | None
        ) = None

        for execution in plan.executions:
            execution_errors = (
                self._execution_errors(
                    execution=execution,
                    timeline_duration_seconds=(
                        plan
                        .timeline_duration_seconds
                    ),
                )
            )

            if previous_execution is not None:
                execution_errors.extend(
                    self._sequence_errors(
                        previous_execution=(
                            previous_execution
                        ),
                        current_execution=(
                            execution
                        ),
                    )
                )

            if execution_errors:
                execution.status = (
                    TransitionExecutionStatus
                    .FAILED
                )

                for message in execution_errors:
                    if message not in (
                        execution.warnings
                    ):
                        execution.warnings.append(
                            message
                        )

                    errors.append(message)
            elif (
                execution.status
                == TransitionExecutionStatus
                .PLANNED
            ):
                execution.status = (
                    TransitionExecutionStatus
                    .VALIDATED
                )

            previous_execution = execution

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

        if errors:
            plan.metadata[
                "validation_errors"
            ] = self._unique_text(
                errors
            )
        else:
            plan.metadata.pop(
                "validation_errors",
                None,
            )

        plan.refresh_summary()

        plan.is_valid = (
            len(errors) == 0
            and plan.failed_count == 0
        )

        plan.is_render_ready = (
            plan.is_valid
            and plan.ready_execution_count
            == plan.transition_count
        )

        plan.metadata[
            "validation_performed"
        ] = True

        plan.metadata[
            "validation_error_count"
        ] = len(
            self._unique_text(errors)
        )

        return plan

    def mark_ready(
        self,
        plan: TransitionExecutionPlan,
    ) -> TransitionExecutionPlan:
        """Mark every validated transition as renderer-ready."""

        self.validate_plan(
            plan
        )

        if not plan.is_valid:
            raise ValueError(
                "Invalid transition execution plan "
                "cannot be marked ready."
            )

        for execution in plan.executions:
            if (
                execution.status
                == TransitionExecutionStatus
                .VALIDATED
            ):
                execution.status = (
                    TransitionExecutionStatus
                    .READY
                )

        plan.refresh_summary()

        plan.is_valid = (
            plan.failed_count == 0
        )

        plan.is_render_ready = (
            plan.is_valid
            and plan.ready_execution_count
            == plan.transition_count
        )

        plan.metadata[
            "marked_ready"
        ] = True

        return plan

    def mark_applied(
        self,
        plan: TransitionExecutionPlan,
        *,
        execution_id: str,
        renderer: str,
        renderer_metadata: (
            dict[str, Any] | None
        ) = None,
    ) -> TransitionExecution:
        """Mark one ready transition as applied by a renderer."""

        cleaned_execution_id = (
            execution_id.strip()
        )

        if not cleaned_execution_id:
            raise ValueError(
                "Transition execution ID "
                "cannot be empty."
            )

        cleaned_renderer = (
            renderer.strip()
        )

        if not cleaned_renderer:
            raise ValueError(
                "Applied transition requires "
                "a renderer name."
            )

        execution = self._find_execution(
            plan=plan,
            execution_id=(
                cleaned_execution_id
            ),
        )

        if execution.status not in {
            TransitionExecutionStatus.READY,
            TransitionExecutionStatus.APPLIED,
        }:
            raise ValueError(
                "Only ready transition executions "
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
            TransitionExecutionStatus.APPLIED
        )

        plan.refresh_summary()

        plan.metadata[
            "applied_transition_count"
        ] = plan.applied_count

        return execution

    def mark_all_applied(
        self,
        plan: TransitionExecutionPlan,
        *,
        renderer: str,
        renderer_metadata: (
            dict[str, Any] | None
        ) = None,
    ) -> list[TransitionExecution]:
        """Mark all ready transitions as applied."""

        cleaned_renderer = (
            renderer.strip()
        )

        if not cleaned_renderer:
            raise ValueError(
                "Applied transitions require "
                "a renderer name."
            )

        if not plan.is_render_ready:
            raise ValueError(
                "Transition execution plan must be "
                "render-ready before application."
            )

        applied: list[
            TransitionExecution
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
        plan: TransitionExecutionPlan,
        *,
        execution_id: str,
        error_message: str,
        failure_metadata: (
            dict[str, Any] | None
        ) = None,
    ) -> TransitionExecution:
        """Mark one transition execution as failed."""

        cleaned_error_message = (
            error_message.strip()
        )

        if not cleaned_error_message:
            raise ValueError(
                "Transition failure message "
                "cannot be empty."
            )

        execution = self._find_execution(
            plan=plan,
            execution_id=(
                execution_id
            ),
        )

        execution.status = (
            TransitionExecutionStatus.FAILED
        )

        failure_warning = (
            "Transition execution failed: "
            f"{cleaned_error_message}"
        )

        if (
            failure_warning
            not in execution.warnings
        ):
            execution.warnings.append(
                failure_warning
            )

        execution.metadata[
            "failure_message"
        ] = cleaned_error_message

        execution.metadata[
            "failure_details"
        ] = dict(
            failure_metadata or {}
        )

        plan.warnings = self._unique_text(
            [
                *plan.warnings,
                failure_warning,
            ]
        )

        plan.refresh_summary()

        plan.is_valid = False
        plan.is_render_ready = False

        return execution

    def summary(
        self,
        plan: TransitionExecutionPlan,
    ) -> dict[str, Any]:
        """Return a serializable transition plan summary."""

        plan.refresh_summary()

        return {
            "plan_id": str(plan.id),
            "schema_version": (
                plan.schema_version
            ),
            "timeline_duration_seconds": (
                plan.timeline_duration_seconds
            ),
            "scene_count": plan.scene_count,
            "transition_count": (
                plan.transition_count
            ),
            "timed_transition_count": (
                plan.timed_transition_count
            ),
            "cut_transition_count": (
                plan.cut_transition_count
            ),
            "overlap_transition_count": (
                plan.overlap_transition_count
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
            "is_valid": plan.is_valid,
            "is_render_ready": (
                plan.is_render_ready
            ),
            "warning_count": len(
                plan.warnings
            ),
            "warnings": list(
                plan.warnings
            ),
            "metadata": dict(
                plan.metadata
            ),
            "executions": [
                {
                    "execution_id": str(
                        execution.id
                    ),
                    "status": (
                        execution.status.value
                    ),
                    "placement": (
                        execution.placement.value
                    ),
                    "direction": (
                        execution.direction.value
                    ),
                    "preset_id": (
                        execution.preset_id
                    ),
                    "transition_type": (
                        execution.transition_type
                    ),
                    "source_scene_number": (
                        execution
                        .source_scene_number
                    ),
                    "target_scene_number": (
                        execution
                        .target_scene_number
                    ),
                    "start_time_seconds": (
                        execution
                        .start_time_seconds
                    ),
                    "end_time_seconds": (
                        execution
                        .end_time_seconds
                    ),
                    "duration_seconds": (
                        execution
                        .duration_seconds
                    ),
                    "requires_overlap": (
                        execution
                        .requires_overlap
                    ),
                    "warnings": list(
                        execution.warnings
                    ),
                }
                for execution in plan.executions
            ],
        }

    @staticmethod
    def _track_items(
        *,
        timeline: VideoTimeline,
        track_index: int,
    ) -> list[VideoTimelineItem]:
        """Return enabled items for one track in playback order."""

        return sorted(
            (
                item
                for item in timeline.items
                if (
                    item.enabled
                    and item.track_index
                    == track_index
                )
            ),
            key=lambda item: (
                item.start_time_seconds,
                item.end_time_seconds,
                item.layer_index,
                item.scene_number,
            ),
        )

    @staticmethod
    def _validate_items(
        items: list[VideoTimelineItem],
    ) -> None:
        """Validate timeline-item transition prerequisites."""

        scene_numbers: set[int] = set()

        for item in items:
            if item.scene_number in scene_numbers:
                raise ValueError(
                    "Transition planning does not "
                    "allow duplicate scene numbers."
                )

            scene_numbers.add(
                item.scene_number
            )

            if item.editing_blueprint is None:
                raise ValueError(
                    "Transition planning requires "
                    "editing blueprints for every scene."
                )

            if not (
                item.editing_blueprint
                .is_resolved
            ):
                raise ValueError(
                    "Transition planning requires "
                    "resolved editing blueprints."
                )

            if item.duration_seconds <= 0.0:
                raise ValueError(
                    "Transition planning requires "
                    "positive timeline-item duration."
                )

    @staticmethod
    def _require_blueprint(
        item: VideoTimelineItem,
    ):
        """Return one resolved editing blueprint."""

        blueprint = item.editing_blueprint

        if blueprint is None:
            raise ValueError(
                "Timeline item does not contain "
                "an editing blueprint."
            )

        if not blueprint.is_resolved:
            raise ValueError(
                "Timeline item contains an unresolved "
                "editing blueprint."
            )

        if (
            blueprint.scene_number
            != item.scene_number
        ):
            raise ValueError(
                "Editing blueprint scene number does "
                "not match its timeline item."
            )

        return blueprint

    @staticmethod
    def _transition_type(
        instruction: ResolvedTransitionInstruction,
    ) -> str:
        """Resolve a normalized transition implementation type."""

        implementation_type = (
            instruction
            .preset
            .implementation
            .get("type")
        )

        if isinstance(
            implementation_type,
            str,
        ):
            cleaned_type = (
                implementation_type
                .strip()
                .lower()
            )

            if cleaned_type:
                return cleaned_type

        return (
            instruction
            .preset
            .resolved_preset_id
            .split(
                ".",
                maxsplit=1,
            )[-1]
            .strip()
            .lower()
        )

    def _requires_overlap(
        self,
        *,
        instruction: ResolvedTransitionInstruction,
        transition_type: str,
    ) -> bool:
        """Determine whether a transition consumes clip overlap."""

        configured_value = (
            instruction
            .preset
            .implementation
            .get("requires_overlap")
        )

        if isinstance(
            configured_value,
            bool,
        ):
            return configured_value

        return (
            transition_type
            in self.OVERLAP_TRANSITION_TYPES
        )

    @staticmethod
    def _normalized_duration(
        *,
        instruction: ResolvedTransitionInstruction,
        maximum_duration: float,
        context: str,
    ) -> float:
        """Validate and normalize one transition duration."""

        duration = float(
            instruction.duration_seconds
        )

        transition_type = (
            TransitionExecutionService
            ._transition_type(
                instruction
            )
        )

        if transition_type == "cut":
            return 0.0

        if duration <= 0.0:
            default_duration = (
                instruction
                .preset
                .implementation
                .get(
                    "default_duration_seconds"
                )
            )

            if isinstance(
                default_duration,
                (int, float),
            ):
                duration = float(
                    default_duration
                )

        if duration <= 0.0:
            raise ValueError(
                f"{context.capitalize()} requires "
                "a positive duration."
            )

        if (
            duration
            > (
                maximum_duration
                + TransitionExecutionService
                .TIME_TOLERANCE_SECONDS
            )
        ):
            raise ValueError(
                f"{context.capitalize()} duration "
                "exceeds available scene timing."
            )

        return duration

    @staticmethod
    def _maximum_between_duration(
        *,
        source_item: VideoTimelineItem,
        target_item: VideoTimelineItem,
        requires_overlap: bool,
    ) -> float:
        """Return maximum safe duration at a scene boundary."""

        source_duration = (
            source_item.duration_seconds
        )

        target_duration = (
            target_item.duration_seconds
        )

        if requires_overlap:
            return min(
                source_duration,
                target_duration,
            )

        return (
            2.0
            * min(
                source_duration,
                target_duration,
            )
        )

    @staticmethod
    def _between_timing(
        *,
        boundary_time: float,
        duration_seconds: float,
        source_item: VideoTimelineItem,
        target_item: VideoTimelineItem,
        requires_overlap: bool,
    ) -> tuple[
        float,
        float,
        float | None,
        float | None,
    ]:
        """Calculate normalized timing for a boundary transition."""

        if duration_seconds == 0.0:
            return (
                boundary_time,
                boundary_time,
                None,
                None,
            )

        if requires_overlap:
            start_time = (
                boundary_time
                - duration_seconds
            )

            end_time = boundary_time

            if (
                start_time
                < (
                    source_item.start_time_seconds
                    - TransitionExecutionService
                    .TIME_TOLERANCE_SECONDS
                )
            ):
                raise ValueError(
                    "Overlap transition begins before "
                    "the source scene."
                )

            return (
                start_time,
                end_time,
                start_time,
                end_time,
            )

        half_duration = (
            duration_seconds / 2.0
        )

        start_time = (
            boundary_time
            - half_duration
        )

        end_time = (
            boundary_time
            + half_duration
        )

        if (
            start_time
            < (
                source_item.start_time_seconds
                - TransitionExecutionService
                .TIME_TOLERANCE_SECONDS
            )
        ):
            raise ValueError(
                "Transition begins before "
                "the source scene."
            )

        if (
            end_time
            > (
                target_item.end_time_seconds
                + TransitionExecutionService
                .TIME_TOLERANCE_SECONDS
            )
        ):
            raise ValueError(
                "Transition ends after "
                "the target scene."
            )

        return (
            start_time,
            end_time,
            None,
            None,
        )

    @staticmethod
    def _select_boundary_instruction(
        *,
        source_instruction: (
            ResolvedTransitionInstruction
        ),
        target_instruction: (
            ResolvedTransitionInstruction
        ),
        source_scene_number: int,
        target_scene_number: int,
    ) -> tuple[
        ResolvedTransitionInstruction,
        list[str],
    ]:
        """
        Select one transition instruction for a scene boundary.

        Policy:

        - Matching preset IDs use the longer configured duration.
        - A non-cut transition is preferred over a cut.
        - Conflicting non-cut transitions prefer the incoming
          target-scene instruction and produce a warning.
        """

        source_id = (
            source_instruction
            .preset
            .resolved_preset_id
        )

        target_id = (
            target_instruction
            .preset
            .resolved_preset_id
        )

        warnings: list[str] = []

        if source_id == target_id:
            if (
                target_instruction.duration_seconds
                >= source_instruction.duration_seconds
            ):
                return (
                    target_instruction,
                    warnings,
                )

            return (
                source_instruction,
                warnings,
            )

        source_is_cut = (
            source_id == "transition.cut"
            or (
                TransitionExecutionService
                ._transition_type(
                    source_instruction
                )
                == "cut"
            )
        )

        target_is_cut = (
            target_id == "transition.cut"
            or (
                TransitionExecutionService
                ._transition_type(
                    target_instruction
                )
                == "cut"
            )
        )

        if source_is_cut and not target_is_cut:
            return (
                target_instruction,
                warnings,
            )

        if target_is_cut and not source_is_cut:
            return (
                source_instruction,
                warnings,
            )

        warnings.append(
            "Conflicting transition instructions "
            f"between scenes {source_scene_number} "
            f"and {target_scene_number}. "
            f"Incoming target transition '{target_id}' "
            f"was selected over outgoing source "
            f"transition '{source_id}'."
        )

        return (
            target_instruction,
            warnings,
        )

    @staticmethod
    def _instruction_warnings(
        *,
        instruction: ResolvedTransitionInstruction,
        context: str,
    ) -> list[str]:
        """Return warnings derived from preset resolution."""

        warnings: list[str] = []

        if (
            instruction
            .preset
            .used_fallback
        ):
            warnings.append(
                f"The {context} transition uses "
                "a fallback preset."
            )

        return warnings

    @staticmethod
    def _execution_errors(
        *,
        execution: TransitionExecution,
        timeline_duration_seconds: float,
    ) -> list[str]:
        """Return validation errors for one execution."""

        errors: list[str] = []

        if (
            execution.start_time_seconds
            < 0.0
        ):
            errors.append(
                "Transition execution begins before "
                "the timeline."
            )

        if (
            execution.end_time_seconds
            > (
                timeline_duration_seconds
                + TransitionExecutionService
                .TIME_TOLERANCE_SECONDS
            )
        ):
            errors.append(
                "Transition execution ends after "
                "the timeline."
            )

        if (
            execution.duration_seconds == 0.0
            and not execution.is_cut
        ):
            errors.append(
                "A non-cut transition cannot use "
                "zero duration."
            )

        if (
            execution.is_cut
            and execution.duration_seconds
            != 0.0
        ):
            errors.append(
                "A cut transition must use "
                "zero duration."
            )

        if (
            execution.requires_overlap
            and (
                execution
                .overlap_start_seconds
                is None
                or execution
                .overlap_end_seconds
                is None
            )
        ):
            errors.append(
                "Overlap transition is missing "
                "overlap timing."
            )

        if (
            execution.placement
            == TransitionPlacement.BETWEEN_SCENES
            and (
                execution.source_scene_number
                is None
                or execution.target_scene_number
                is None
            )
        ):
            errors.append(
                "Between-scene transition lacks "
                "source or target scene mapping."
            )

        return errors

    @staticmethod
    def _sequence_errors(
        *,
        previous_execution: TransitionExecution,
        current_execution: TransitionExecution,
    ) -> list[str]:
        """Return ordering conflicts between executions."""

        errors: list[str] = []

        if (
            current_execution
            .start_time_seconds
            + (
                TransitionExecutionService
                .TIME_TOLERANCE_SECONDS
            )
            < previous_execution
            .start_time_seconds
        ):
            errors.append(
                "Transition executions are not "
                "in playback order."
            )

        if (
            previous_execution.placement
            == TransitionPlacement.TIMELINE_OUT
        ):
            errors.append(
                "No transition may appear after "
                "the timeline-out transition."
            )

        if (
            current_execution.placement
            == TransitionPlacement.TIMELINE_IN
        ):
            errors.append(
                "Timeline-in transition must be "
                "the first execution."
            )

        return errors

    @staticmethod
    def _create_plan(
        *,
        executions: list[
            TransitionExecution
        ],
        timeline: VideoTimeline,
        scene_count: int,
        warnings: list[str],
        metadata: dict[str, Any],
    ) -> TransitionExecutionPlan:
        """Create a model-valid initial execution plan."""

        ordered_executions = sorted(
            executions,
            key=lambda execution: (
                execution.start_time_seconds,
                execution.end_time_seconds,
                execution.placement.value,
                execution.source_scene_number
                or 0,
                execution.target_scene_number
                or 0,
            ),
        )

        transition_count = len(
            ordered_executions
        )

        timed_count = sum(
            1
            for execution
            in ordered_executions
            if execution.is_timed
        )

        cut_count = sum(
            1
            for execution
            in ordered_executions
            if execution.is_cut
        )

        overlap_count = sum(
            1
            for execution
            in ordered_executions
            if execution.requires_overlap
        )

        ready_count = sum(
            1
            for execution
            in ordered_executions
            if execution.is_ready
        )

        return TransitionExecutionPlan(
            executions=ordered_executions,
            timeline_duration_seconds=(
                timeline.calculate_duration()
            ),
            scene_count=scene_count,
            transition_count=(
                transition_count
            ),
            timed_transition_count=(
                timed_count
            ),
            cut_transition_count=(
                cut_count
            ),
            overlap_transition_count=(
                overlap_count
            ),
            ready_execution_count=(
                ready_count
            ),
            is_valid=True,
            is_render_ready=(
                transition_count
                == ready_count
            ),
            warnings=(
                TransitionExecutionService
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
        plan: TransitionExecutionPlan,
        execution_id: str,
    ) -> TransitionExecution:
        """Return one transition execution by ID."""

        cleaned_execution_id = (
            execution_id.strip()
        )

        if not cleaned_execution_id:
            raise ValueError(
                "Transition execution ID "
                "cannot be empty."
            )

        matches = [
            execution
            for execution in plan.executions
            if str(execution.id)
            == cleaned_execution_id
        ]

        if not matches:
            raise KeyError(
                "Transition execution was not found: "
                f"{cleaned_execution_id}"
            )

        if len(matches) > 1:
            raise ValueError(
                "Multiple transition executions "
                "share the same ID."
            )

        return matches[0]

    @staticmethod
    def _unique_text(
        values: list[str],
    ) -> list[str]:
        """Return normalized unique text values."""

        cleaned: list[str] = []

        for value in values:
            normalized = value.strip()

            if (
                normalized
                and normalized not in cleaned
            ):
                cleaned.append(
                    normalized
                )

        return cleaned