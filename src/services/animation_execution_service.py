from __future__ import annotations

from typing import Any

from src.models.animation_execution import (
    AnimationExecution,
    AnimationExecutionPlan,
    AnimationExecutionStatus,
)
from src.models.resolved_editing_blueprint import (
    ResolvedAnimationInstruction,
)
from src.models.video_timeline import VideoTimeline
from src.models.video_timeline_item import (
    VideoTimelineItem,
)
from src.services.timeline_validation_service import (
    TimelineValidationService,
)


class AnimationExecutionService:
    """
    Build provider-independent animation execution plans.

    Scene-local resolved animation instructions are converted into
    absolute timeline timing. Renderer-specific implementation is
    deferred to the render-adapter layer.
    """

    TIME_TOLERANCE_SECONDS = 0.001

    def __init__(
        self,
        *,
        timeline_validation_service: TimelineValidationService | None = None,
    ) -> None:
        self.timeline_validation_service = (
            timeline_validation_service or TimelineValidationService()
        )

    def build_plan(
        self,
        timeline: VideoTimeline,
        *,
        track_index: int | None = None,
        validate_timeline: bool = True,
        mark_ready: bool = True,
    ) -> AnimationExecutionPlan:
        """Build animations for all enabled timeline scenes."""

        if track_index is not None and track_index < 0:
            raise ValueError("Animation plan track index " "cannot be negative.")

        if validate_timeline:
            validation_result = self.timeline_validation_service.validate(
                timeline,
                require_gap_free_primary_track=True,
                require_editing_blueprints=True,
                warn_on_blueprint_fallbacks=True,
            )

            if not validation_result.is_valid:
                raise ValueError(
                    "Video timeline is not valid for "
                    "animation execution planning. "
                    + " ".join(issue.message for issue in validation_result.errors)
                )

        items = [
            item
            for item in timeline.ordered_items()
            if (track_index is None or item.track_index == track_index)
        ]

        if not items:
            raise ValueError(
                "Animation execution planning requires "
                "at least one enabled timeline item."
            )

        executions: list[AnimationExecution] = []

        warnings: list[str] = []

        for item in items:
            scene_executions = self.build_scene_animations(
                item=item,
            )

            executions.extend(scene_executions)

            warnings.extend(
                warning
                for execution in scene_executions
                for warning in execution.warnings
            )

        plan = self._create_plan(
            timeline=timeline,
            executions=executions,
            warnings=warnings,
            metadata={
                "track_index": track_index,
                "timeline_validation_performed": (validate_timeline),
            },
        )

        self.validate_plan(plan)

        if mark_ready:
            self.mark_ready(plan)

        return plan

    def build_scene_animations(
        self,
        *,
        item: VideoTimelineItem,
    ) -> list[AnimationExecution]:
        """Build enabled animations for one scene."""

        blueprint = item.editing_blueprint

        if blueprint is None:
            raise ValueError(
                "Animation execution planning requires " "an editing blueprint."
            )

        if not blueprint.is_resolved:
            raise ValueError(
                "Animation execution planning requires " "a resolved editing blueprint."
            )

        if blueprint.scene_number != item.scene_number:
            raise ValueError(
                "Animation blueprint scene number does " "not match timeline item."
            )

        executions: list[AnimationExecution] = []

        for instruction in blueprint.animations:
            if not instruction.enabled:
                continue

            preset_id = instruction.preset.resolved_preset_id

            if preset_id == "animation.none":
                continue

            executions.append(
                self.build_execution(
                    item=item,
                    instruction=instruction,
                )
            )

        return executions

    def build_execution(
        self,
        *,
        item: VideoTimelineItem,
        instruction: ResolvedAnimationInstruction,
    ) -> AnimationExecution:
        """Build one normalized animation execution."""

        if not instruction.enabled:
            raise ValueError("Disabled animation cannot " "produce an execution.")

        preset = instruction.preset

        preset_id = preset.resolved_preset_id

        if not preset_id.startswith("animation."):
            raise ValueError("Animation execution requires " "an animation preset.")

        implementation = dict(preset.implementation)

        animation_type = self._animation_type(
            preset_id=preset_id,
            implementation=implementation,
        )

        target = self._optional_text(implementation.get("target"))

        scene_duration = item.duration_seconds

        local_start = float(instruction.start_offset_seconds)

        if local_start >= scene_duration:
            raise ValueError("Animation start offset must occur " "before scene end.")

        duration = (
            float(instruction.duration_seconds)
            if (instruction.duration_seconds is not None)
            else (scene_duration - local_start)
        )

        if duration <= 0.0:
            raise ValueError("Animation duration must be positive.")

        local_end = local_start + duration

        if local_end > (scene_duration + self.TIME_TOLERANCE_SECONDS):
            raise ValueError("Animation execution extends " "beyond scene duration.")

        warnings: list[str] = []

        if preset.used_fallback:
            warnings.append("Animation execution uses " "a fallback preset.")

        return AnimationExecution(
            status=(AnimationExecutionStatus.PLANNED),
            scene_number=item.scene_number,
            track_index=item.track_index,
            layer_index=item.layer_index,
            preset_id=preset_id,
            animation_type=animation_type,
            target=target,
            intensity=instruction.intensity,
            start_time_seconds=(item.start_time_seconds + local_start),
            end_time_seconds=(item.start_time_seconds + local_end),
            duration_seconds=duration,
            scene_start_time_seconds=(item.start_time_seconds),
            scene_end_time_seconds=(item.end_time_seconds),
            scene_duration_seconds=(scene_duration),
            local_start_offset_seconds=(local_start),
            local_end_offset_seconds=(local_end),
            implementation=implementation,
            warnings=warnings,
            metadata={
                "timeline_item_id": str(item.id),
                "directive_path": (preset.directive_path),
                "found_exact_match": (preset.found_exact_match),
                "used_fallback": (preset.used_fallback),
            },
        )

    def validate_plan(
        self,
        plan: AnimationExecutionPlan,
    ) -> AnimationExecutionPlan:
        """Validate all animation executions."""

        errors: list[str] = []

        for execution in plan.executions:
            execution_errors = self._execution_errors(
                execution=execution,
                timeline_duration_seconds=(plan.timeline_duration_seconds),
            )

            if execution_errors:
                execution.status = AnimationExecutionStatus.FAILED

                for message in execution_errors:
                    if message not in execution.warnings:
                        execution.warnings.append(message)

                    errors.append(message)

            elif execution.status == AnimationExecutionStatus.PLANNED:
                execution.status = AnimationExecutionStatus.VALIDATED

        plan.warnings = self._unique_text(
            [
                *plan.warnings,
                *[
                    warning
                    for execution in plan.executions
                    for warning in execution.warnings
                ],
            ]
        )

        plan.metadata["validation_errors"] = self._unique_text(errors)

        plan.refresh_summary()

        plan.is_valid = len(errors) == 0 and plan.failed_count == 0

        plan.is_render_ready = (
            plan.is_valid
            and (plan.ready_execution_count + plan.skipped_execution_count)
            == plan.execution_count
        )

        return plan

    def mark_ready(
        self,
        plan: AnimationExecutionPlan,
    ) -> AnimationExecutionPlan:
        """Mark validated animations as ready."""

        self.validate_plan(plan)

        if not plan.is_valid:
            raise ValueError(
                "Invalid animation execution plan " "cannot be marked ready."
            )

        for execution in plan.executions:
            if execution.status == AnimationExecutionStatus.VALIDATED:
                execution.status = AnimationExecutionStatus.READY

        plan.refresh_summary()

        return plan

    def mark_applied(
        self,
        plan: AnimationExecutionPlan,
        *,
        execution_id: str,
        renderer: str,
        renderer_metadata: dict[str, Any] | None = None,
    ) -> AnimationExecution:
        """Mark one ready animation as applied."""

        cleaned_renderer = renderer.strip()

        if not cleaned_renderer:
            raise ValueError("Applied animation requires " "a renderer name.")

        execution = self._find_execution(
            plan=plan,
            execution_id=execution_id,
        )

        if execution.status not in {
            AnimationExecutionStatus.READY,
            AnimationExecutionStatus.APPLIED,
        }:
            raise ValueError(
                "Only ready animation executions " "can be marked applied."
            )

        execution.metadata["renderer"] = cleaned_renderer

        execution.metadata["renderer_metadata"] = dict(renderer_metadata or {})

        execution.status = AnimationExecutionStatus.APPLIED

        plan.refresh_summary()

        return execution

    def mark_all_applied(
        self,
        plan: AnimationExecutionPlan,
        *,
        renderer: str,
        renderer_metadata: dict[str, Any] | None = None,
    ) -> list[AnimationExecution]:
        """Mark all ready animations as applied."""

        cleaned_renderer = renderer.strip()

        if not cleaned_renderer:
            raise ValueError("Applied animations require " "a renderer name.")

        if not plan.is_render_ready:
            raise ValueError(
                "Animation execution plan must be " "render-ready before application."
            )

        applied: list[AnimationExecution] = []

        for execution in plan.executions:
            if execution.status == AnimationExecutionStatus.SKIPPED:
                continue

            applied.append(
                self.mark_applied(
                    plan,
                    execution_id=str(execution.id),
                    renderer=cleaned_renderer,
                    renderer_metadata=(renderer_metadata),
                )
            )

        return applied

    def mark_failed(
        self,
        plan: AnimationExecutionPlan,
        *,
        execution_id: str,
        error_message: str,
        failure_metadata: dict[str, Any] | None = None,
    ) -> AnimationExecution:
        """Mark one animation as failed."""

        cleaned_message = error_message.strip()

        if not cleaned_message:
            raise ValueError("Animation failure message " "cannot be empty.")

        execution = self._find_execution(
            plan=plan,
            execution_id=execution_id,
        )

        execution.status = AnimationExecutionStatus.FAILED

        execution.metadata["failure_message"] = cleaned_message

        execution.metadata["failure_details"] = dict(failure_metadata or {})

        warning = "Animation execution failed: " f"{cleaned_message}"

        if warning not in execution.warnings:
            execution.warnings.append(warning)

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
        plan: AnimationExecutionPlan,
    ) -> dict[str, Any]:
        """Return serializable animation-plan summary."""

        plan.refresh_summary()

        return {
            "plan_id": str(plan.id),
            "schema_version": (plan.schema_version),
            "timeline_duration_seconds": (plan.timeline_duration_seconds),
            "scene_count": (plan.scene_count),
            "execution_count": (plan.execution_count),
            "active_execution_count": (plan.active_execution_count),
            "skipped_execution_count": (plan.skipped_execution_count),
            "ready_execution_count": (plan.ready_execution_count),
            "applied_count": (plan.applied_count),
            "failed_count": (plan.failed_count),
            "is_valid": (plan.is_valid),
            "is_render_ready": (plan.is_render_ready),
            "warnings": list(plan.warnings),
            "metadata": dict(plan.metadata),
        }

    @staticmethod
    def _animation_type(
        *,
        preset_id: str,
        implementation: dict[str, Any],
    ) -> str:
        """Resolve normalized animation type."""

        animation = implementation.get("animation")

        if isinstance(
            animation,
            str,
        ):
            cleaned = animation.strip().lower()

            if cleaned:
                return cleaned

        return (
            preset_id.split(
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

        cleaned = value.strip().lower()

        return cleaned or None

    @staticmethod
    def _execution_errors(
        *,
        execution: AnimationExecution,
        timeline_duration_seconds: float,
    ) -> list[str]:
        """Return validation errors for one execution."""

        errors: list[str] = []

        if execution.start_time_seconds < execution.scene_start_time_seconds - 0.001:
            errors.append("Animation begins before its scene.")

        if execution.end_time_seconds > execution.scene_end_time_seconds + 0.001:
            errors.append("Animation ends after its scene.")

        if execution.end_time_seconds > timeline_duration_seconds + 0.001:
            errors.append("Animation ends after video timeline.")

        if execution.duration_seconds <= 0.0:
            errors.append("Animation requires positive duration.")

        return errors

    @staticmethod
    def _create_plan(
        *,
        timeline: VideoTimeline,
        executions: list[AnimationExecution],
        warnings: list[str],
        metadata: dict[str, Any],
    ) -> AnimationExecutionPlan:
        """Create initial animation execution plan."""

        ordered = sorted(
            executions,
            key=lambda execution: (
                execution.start_time_seconds,
                execution.track_index,
                execution.layer_index,
                execution.scene_number,
                execution.preset_id,
            ),
        )

        execution_count = len(ordered)

        active_count = sum(1 for execution in ordered if not execution.is_none)

        ready_count = sum(1 for execution in ordered if execution.is_ready)

        return AnimationExecutionPlan(
            executions=ordered,
            timeline_duration_seconds=(timeline.calculate_duration()),
            scene_count=len({execution.scene_number for execution in ordered}),
            execution_count=(execution_count),
            active_execution_count=(active_count),
            skipped_execution_count=0,
            ready_execution_count=(ready_count),
            is_valid=True,
            is_render_ready=(ready_count == execution_count),
            warnings=(AnimationExecutionService._unique_text(warnings)),
            metadata=dict(metadata),
        )

    @staticmethod
    def _find_execution(
        *,
        plan: AnimationExecutionPlan,
        execution_id: str,
    ) -> AnimationExecution:
        """Return one animation execution by ID."""

        cleaned = execution_id.strip()

        if not cleaned:
            raise ValueError("Animation execution ID " "cannot be empty.")

        matches = [
            execution for execution in plan.executions if str(execution.id) == cleaned
        ]

        if not matches:
            raise KeyError("Animation execution was not found: " f"{cleaned}")

        if len(matches) > 1:
            raise ValueError("Multiple animation executions " "share the same ID.")

        return matches[0]

    @staticmethod
    def _unique_text(
        values: list[str],
    ) -> list[str]:
        """Return normalized unique text."""

        cleaned: list[str] = []

        for value in values:
            normalized = value.strip()

            if normalized and normalized not in cleaned:
                cleaned.append(normalized)

        return cleaned
