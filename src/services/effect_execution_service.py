from __future__ import annotations

from typing import Any

from src.models.editing_directives import (
    DirectiveTimingMode,
)
from src.models.effect_execution import (
    EffectExecution,
    EffectExecutionPlan,
    EffectExecutionStatus,
)
from src.models.resolved_editing_blueprint import (
    ResolvedVisualEffectInstruction,
)
from src.models.video_timeline import VideoTimeline
from src.models.video_timeline_item import (
    VideoTimelineItem,
)
from src.services.timeline_validation_service import (
    TimelineValidationService,
)


class EffectExecutionService:
    """
    Build provider-independent visual-effect execution plans.

    Scene-local visual-effect timing is converted into absolute
    video-timeline timing. No renderer-specific command generation
    or FFmpeg execution happens in this service.
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
    ) -> EffectExecutionPlan:
        """Build visual-effect executions for a video timeline."""

        if track_index is not None and track_index < 0:
            raise ValueError("Effect plan track index " "cannot be negative.")

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
                    "visual-effect planning. "
                    + " ".join(issue.message for issue in validation_result.errors)
                )

        items = [
            item
            for item in timeline.ordered_items()
            if (track_index is None or item.track_index == track_index)
        ]

        if not items:
            raise ValueError(
                "Effect execution planning requires "
                "at least one enabled timeline item."
            )

        executions: list[EffectExecution] = []

        plan_warnings: list[str] = []

        for item in items:
            blueprint = item.editing_blueprint

            if blueprint is None:
                raise ValueError(
                    "Effect execution planning requires "
                    "an editing blueprint for every scene."
                )

            if not blueprint.is_resolved:
                raise ValueError(
                    "Effect execution planning requires " "resolved editing blueprints."
                )

            if blueprint.scene_number != item.scene_number:
                raise ValueError(
                    "Editing blueprint scene number " "does not match timeline item."
                )

            scene_executions = self.build_scene_effects(
                item=item,
            )

            executions.extend(scene_executions)

            plan_warnings.extend(
                warning
                for execution in scene_executions
                for warning in execution.warnings
            )

        plan = self._create_plan(
            timeline=timeline,
            executions=executions,
            warnings=plan_warnings,
            metadata={
                "track_index": track_index,
                "timeline_validation_performed": (validate_timeline),
            },
        )

        self.validate_plan(plan)

        if mark_ready:
            self.mark_ready(plan)

        return plan

    def build_scene_effects(
        self,
        *,
        item: VideoTimelineItem,
    ) -> list[EffectExecution]:
        """Build executions for all enabled effects in one scene."""

        blueprint = item.editing_blueprint

        if blueprint is None:
            raise ValueError("Timeline item does not contain " "an editing blueprint.")

        if not blueprint.is_resolved:
            raise ValueError(
                "Timeline item contains an unresolved " "editing blueprint."
            )

        executions: list[EffectExecution] = []

        for instruction in blueprint.visual_effects:
            if not instruction.enabled:
                continue

            preset_id = instruction.preset.resolved_preset_id

            if preset_id == "visual.none":
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
        instruction: ResolvedVisualEffectInstruction,
    ) -> EffectExecution:
        """Build one normalized visual-effect execution."""

        if not instruction.enabled:
            raise ValueError("Disabled visual effects cannot " "produce executions.")

        preset_id = instruction.preset.resolved_preset_id

        if not preset_id.startswith("visual."):
            raise ValueError("Visual effect execution requires " "a visual preset.")

        scene_start = item.start_time_seconds

        scene_end = item.end_time_seconds

        scene_duration = item.duration_seconds

        (
            local_start,
            duration,
            relative_percent,
        ) = self._resolve_local_timing(
            instruction=instruction,
            scene_duration_seconds=(scene_duration),
        )

        global_start = scene_start + local_start

        global_end = global_start + duration

        if global_end > scene_end + self.TIME_TOLERANCE_SECONDS:
            raise ValueError("Visual-effect execution extends " "beyond its scene.")

        effect_type = self._effect_type(instruction)

        warnings = self._instruction_warnings(instruction)

        return EffectExecution(
            status=EffectExecutionStatus.PLANNED,
            scene_number=item.scene_number,
            track_index=item.track_index,
            layer_index=item.layer_index,
            preset_id=preset_id,
            effect_type=effect_type,
            timing_mode=instruction.timing_mode,
            intensity=instruction.intensity,
            start_time_seconds=global_start,
            end_time_seconds=global_end,
            duration_seconds=duration,
            scene_start_time_seconds=scene_start,
            scene_end_time_seconds=scene_end,
            scene_duration_seconds=scene_duration,
            local_start_offset_seconds=(local_start),
            relative_position_percent=(relative_percent),
            implementation=dict(instruction.preset.implementation),
            warnings=warnings,
            metadata={
                "timeline_item_id": str(item.id),
                "directive_path": (instruction.preset.directive_path),
                "found_exact_match": (instruction.preset.found_exact_match),
                "used_fallback": (instruction.preset.used_fallback),
            },
        )

    def validate_plan(
        self,
        plan: EffectExecutionPlan,
    ) -> EffectExecutionPlan:
        """Validate every execution in one effect plan."""

        errors: list[str] = []

        for execution in plan.executions:
            execution_errors = self._execution_errors(
                execution=execution,
                timeline_duration_seconds=(plan.timeline_duration_seconds),
            )

            if execution_errors:
                execution.status = EffectExecutionStatus.FAILED

                for message in execution_errors:
                    if message not in execution.warnings:
                        execution.warnings.append(message)

                    errors.append(message)

            elif execution.status == EffectExecutionStatus.PLANNED:
                execution.status = EffectExecutionStatus.VALIDATED

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

        plan.metadata["validation_performed"] = True

        plan.metadata["validation_errors"] = self._unique_text(errors)

        plan.refresh_summary()

        plan.is_valid = len(errors) == 0 and plan.failed_count == 0

        plan.is_render_ready = (
            plan.is_valid and plan.ready_execution_count == plan.effect_count
        )

        return plan

    def mark_ready(
        self,
        plan: EffectExecutionPlan,
    ) -> EffectExecutionPlan:
        """Mark validated visual effects as renderer-ready."""

        self.validate_plan(plan)

        if not plan.is_valid:
            raise ValueError("Invalid visual-effect plan cannot " "be marked ready.")

        for execution in plan.executions:
            if execution.status == EffectExecutionStatus.VALIDATED:
                execution.status = EffectExecutionStatus.READY

        plan.refresh_summary()

        plan.is_valid = plan.failed_count == 0

        plan.is_render_ready = (
            plan.is_valid and plan.ready_execution_count == plan.effect_count
        )

        plan.metadata["marked_ready"] = True

        return plan

    def mark_applied(
        self,
        plan: EffectExecutionPlan,
        *,
        execution_id: str,
        renderer: str,
        renderer_metadata: dict[str, Any] | None = None,
    ) -> EffectExecution:
        """Mark one ready effect execution as applied."""

        cleaned_renderer = renderer.strip()

        if not cleaned_renderer:
            raise ValueError("Applied visual effect requires " "a renderer name.")

        execution = self._find_execution(
            plan=plan,
            execution_id=execution_id,
        )

        if execution.status not in {
            EffectExecutionStatus.READY,
            EffectExecutionStatus.APPLIED,
        }:
            raise ValueError(
                "Only ready visual-effect executions " "can be marked applied."
            )

        execution.metadata["renderer"] = cleaned_renderer

        execution.metadata["renderer_metadata"] = dict(renderer_metadata or {})

        execution.status = EffectExecutionStatus.APPLIED

        plan.refresh_summary()

        return execution

    def mark_all_applied(
        self,
        plan: EffectExecutionPlan,
        *,
        renderer: str,
        renderer_metadata: dict[str, Any] | None = None,
    ) -> list[EffectExecution]:
        """Mark every ready visual effect as applied."""

        cleaned_renderer = renderer.strip()

        if not cleaned_renderer:
            raise ValueError("Applied visual effects require " "a renderer name.")

        if not plan.is_render_ready:
            raise ValueError(
                "Effect execution plan must be " "render-ready before application."
            )

        applied: list[EffectExecution] = []

        for execution in plan.executions:
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
        plan: EffectExecutionPlan,
        *,
        execution_id: str,
        error_message: str,
        failure_metadata: dict[str, Any] | None = None,
    ) -> EffectExecution:
        """Mark one effect execution as failed."""

        cleaned_message = error_message.strip()

        if not cleaned_message:
            raise ValueError("Visual-effect failure message " "cannot be empty.")

        execution = self._find_execution(
            plan=plan,
            execution_id=execution_id,
        )

        execution.status = EffectExecutionStatus.FAILED

        execution.metadata["failure_message"] = cleaned_message

        execution.metadata["failure_details"] = dict(failure_metadata or {})

        warning = "Visual-effect execution failed: " f"{cleaned_message}"

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
        plan: EffectExecutionPlan,
    ) -> dict[str, Any]:
        """Return a serializable effect-plan summary."""

        plan.refresh_summary()

        return {
            "plan_id": str(plan.id),
            "schema_version": (plan.schema_version),
            "timeline_duration_seconds": (plan.timeline_duration_seconds),
            "scene_count": plan.scene_count,
            "effect_count": plan.effect_count,
            "full_scene_effect_count": (plan.full_scene_effect_count),
            "timed_effect_count": (plan.timed_effect_count),
            "ready_execution_count": (plan.ready_execution_count),
            "applied_count": (plan.applied_count),
            "failed_count": (plan.failed_count),
            "is_valid": plan.is_valid,
            "is_render_ready": (plan.is_render_ready),
            "warning_count": len(plan.warnings),
            "warnings": list(plan.warnings),
            "metadata": dict(plan.metadata),
            "executions": [
                {
                    "execution_id": str(execution.id),
                    "status": (execution.status.value),
                    "scene_number": (execution.scene_number),
                    "preset_id": (execution.preset_id),
                    "effect_type": (execution.effect_type),
                    "timing_mode": (execution.timing_mode.value),
                    "start_time_seconds": (execution.start_time_seconds),
                    "end_time_seconds": (execution.end_time_seconds),
                    "duration_seconds": (execution.duration_seconds),
                    "local_start_offset_seconds": (
                        execution.local_start_offset_seconds
                    ),
                    "relative_position_percent": (execution.relative_position_percent),
                }
                for execution in plan.executions
            ],
        }

    def _resolve_local_timing(
        self,
        *,
        instruction: ResolvedVisualEffectInstruction,
        scene_duration_seconds: float,
    ) -> tuple[
        float,
        float,
        float | None,
    ]:
        """Convert directive timing to local scene seconds."""

        if scene_duration_seconds <= 0.0:
            raise ValueError(
                "Visual-effect planning requires " "positive scene duration."
            )

        timing_mode = instruction.timing_mode

        duration = (
            float(instruction.duration_seconds)
            if instruction.duration_seconds is not None
            else None
        )

        relative_percent: float | None = instruction.relative_position_percent

        if timing_mode == DirectiveTimingMode.FULL_SCENE:
            return (
                0.0,
                scene_duration_seconds,
                None,
            )

        if timing_mode == DirectiveTimingMode.SCENE_START:
            resolved_duration = (
                duration if duration is not None else scene_duration_seconds
            )

            return (
                0.0,
                self._bounded_duration(
                    start_offset_seconds=0.0,
                    duration_seconds=(resolved_duration),
                    scene_duration_seconds=(scene_duration_seconds),
                ),
                None,
            )

        if timing_mode == DirectiveTimingMode.SCENE_MIDDLE:
            resolved_duration = (
                duration if duration is not None else scene_duration_seconds
            )

            local_start = max(
                0.0,
                (scene_duration_seconds - resolved_duration) / 2.0,
            )

            return (
                local_start,
                self._bounded_duration(
                    start_offset_seconds=(local_start),
                    duration_seconds=(resolved_duration),
                    scene_duration_seconds=(scene_duration_seconds),
                ),
                None,
            )

        if timing_mode == DirectiveTimingMode.SCENE_END:
            resolved_duration = (
                duration if duration is not None else scene_duration_seconds
            )

            if resolved_duration > scene_duration_seconds:
                raise ValueError(
                    "Scene-end visual-effect duration " "exceeds scene duration."
                )

            local_start = scene_duration_seconds - resolved_duration

            return (
                local_start,
                resolved_duration,
                None,
            )

        if timing_mode == DirectiveTimingMode.ABSOLUTE_SECONDS:
            local_start = float(instruction.start_offset_seconds)

            resolved_duration = (
                duration
                if duration is not None
                else (scene_duration_seconds - local_start)
            )

            return (
                local_start,
                self._bounded_duration(
                    start_offset_seconds=(local_start),
                    duration_seconds=(resolved_duration),
                    scene_duration_seconds=(scene_duration_seconds),
                ),
                None,
            )

        if timing_mode == DirectiveTimingMode.RELATIVE_PERCENT:
            if relative_percent is None:
                raise ValueError(
                    "Relative-percent visual effect " "requires a percentage position."
                )

            local_start = scene_duration_seconds * relative_percent / 100.0

            if local_start >= scene_duration_seconds:
                raise ValueError(
                    "Relative visual-effect position " "must occur before scene end."
                )

            resolved_duration = (
                duration
                if duration is not None
                else (scene_duration_seconds - local_start)
            )

            return (
                local_start,
                self._bounded_duration(
                    start_offset_seconds=(local_start),
                    duration_seconds=(resolved_duration),
                    scene_duration_seconds=(scene_duration_seconds),
                ),
                relative_percent,
            )

        raise ValueError("Unsupported visual-effect timing mode.")

    @staticmethod
    def _bounded_duration(
        *,
        start_offset_seconds: float,
        duration_seconds: float,
        scene_duration_seconds: float,
    ) -> float:
        """Validate an effect duration inside its scene."""

        if start_offset_seconds < 0.0:
            raise ValueError("Visual-effect start offset " "cannot be negative.")

        if duration_seconds <= 0.0:
            raise ValueError("Visual-effect duration must " "be positive.")

        if start_offset_seconds >= scene_duration_seconds:
            raise ValueError(
                "Visual-effect start offset " "must occur before scene end."
            )

        if start_offset_seconds + duration_seconds > (
            scene_duration_seconds + EffectExecutionService.TIME_TOLERANCE_SECONDS
        ):
            raise ValueError("Visual-effect duration extends " "beyond scene duration.")

        return duration_seconds

    @staticmethod
    def _effect_type(
        instruction: ResolvedVisualEffectInstruction,
    ) -> str:
        """Resolve a normalized visual-effect type."""

        implementation = instruction.preset.implementation

        for key in (
            "effect",
            "type",
            "filter",
        ):
            value = implementation.get(key)

            if isinstance(
                value,
                str,
            ):
                cleaned = value.strip().lower()

                if cleaned:
                    return cleaned

        return (
            instruction.preset.resolved_preset_id.split(
                ".",
                maxsplit=1,
            )[-1]
            .strip()
            .lower()
        )

    @staticmethod
    def _instruction_warnings(
        instruction: ResolvedVisualEffectInstruction,
    ) -> list[str]:
        """Return warnings derived from resolution metadata."""

        warnings: list[str] = []

        if instruction.preset.used_fallback:
            warnings.append("Visual effect uses a fallback preset.")

        return warnings

    @staticmethod
    def _execution_errors(
        *,
        execution: EffectExecution,
        timeline_duration_seconds: float,
    ) -> list[str]:
        """Return validation errors for one effect."""

        errors: list[str] = []

        if execution.start_time_seconds < execution.scene_start_time_seconds - 0.001:
            errors.append("Visual effect starts before its scene.")

        if execution.end_time_seconds > execution.scene_end_time_seconds + 0.001:
            errors.append("Visual effect ends after its scene.")

        if execution.end_time_seconds > timeline_duration_seconds + 0.001:
            errors.append("Visual effect ends after the timeline.")

        if execution.duration_seconds <= 0.0:
            errors.append("Visual effect requires " "positive duration.")

        return errors

    @staticmethod
    def _create_plan(
        *,
        timeline: VideoTimeline,
        executions: list[EffectExecution],
        warnings: list[str],
        metadata: dict[str, Any],
    ) -> EffectExecutionPlan:
        """Create an initial model-valid effect plan."""

        ordered_executions = sorted(
            executions,
            key=lambda execution: (
                execution.start_time_seconds,
                execution.track_index,
                execution.layer_index,
                execution.scene_number,
                execution.preset_id,
            ),
        )

        effect_count = len(ordered_executions)

        full_scene_count = sum(
            1 for execution in ordered_executions if execution.is_full_scene
        )

        timed_count = effect_count - full_scene_count

        ready_count = sum(1 for execution in ordered_executions if execution.is_ready)

        scene_count = len({execution.scene_number for execution in ordered_executions})

        return EffectExecutionPlan(
            executions=ordered_executions,
            timeline_duration_seconds=(timeline.calculate_duration()),
            scene_count=scene_count,
            effect_count=effect_count,
            full_scene_effect_count=(full_scene_count),
            timed_effect_count=(timed_count),
            ready_execution_count=(ready_count),
            is_valid=True,
            is_render_ready=(ready_count == effect_count),
            warnings=(EffectExecutionService._unique_text(warnings)),
            metadata=dict(metadata),
        )

    @staticmethod
    def _find_execution(
        *,
        plan: EffectExecutionPlan,
        execution_id: str,
    ) -> EffectExecution:
        """Return one visual-effect execution by ID."""

        cleaned_id = execution_id.strip()

        if not cleaned_id:
            raise ValueError("Visual-effect execution ID " "cannot be empty.")

        matches = [
            execution
            for execution in plan.executions
            if str(execution.id) == cleaned_id
        ]

        if not matches:
            raise KeyError("Visual-effect execution " f"was not found: {cleaned_id}")

        if len(matches) > 1:
            raise ValueError("Multiple visual-effect executions " "share the same ID.")

        return matches[0]

    @staticmethod
    def _unique_text(
        values: list[str],
    ) -> list[str]:
        """Return normalized unique text values."""

        cleaned: list[str] = []

        for value in values:
            normalized = value.strip()

            if normalized and normalized not in cleaned:
                cleaned.append(normalized)

        return cleaned
