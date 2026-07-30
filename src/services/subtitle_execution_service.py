from __future__ import annotations

import re
from typing import Any

from src.models.resolved_voice_blueprint import (
    ResolvedVoiceBlueprint,
)
from src.models.subtitle_execution import (
    SubtitleExecution,
    SubtitleExecutionPlan,
    SubtitleExecutionStatus,
    SubtitleTimingSource,
)
from src.models.video_timeline import VideoTimeline
from src.models.video_timeline_item import (
    VideoTimelineItem,
)


class SubtitleExecutionService:
    """
    Build provider-independent subtitle execution plans.

    Until precise word timestamps are available, subtitle timing
    is estimated proportionally from narration text and available
    scene/voice duration.
    """

    TIME_TOLERANCE_SECONDS = 0.001

    def build_plan(
        self,
        timeline: VideoTimeline,
        *,
        voice_blueprints: list[
            ResolvedVoiceBlueprint
        ],
        minimum_segment_duration_seconds: float = 0.8,
        maximum_segment_duration_seconds: float = 6.0,
        mark_ready: bool = True,
    ) -> SubtitleExecutionPlan:
        """Build subtitle executions for enabled timeline scenes."""

        if minimum_segment_duration_seconds <= 0.0:
            raise ValueError(
                "Minimum subtitle duration must "
                "be positive."
            )

        if (
            maximum_segment_duration_seconds
            < minimum_segment_duration_seconds
        ):
            raise ValueError(
                "Maximum subtitle duration cannot be "
                "less than minimum subtitle duration."
            )

        blueprint_map = {
            blueprint.scene_number: blueprint
            for blueprint in voice_blueprints
        }

        if len(blueprint_map) != len(
            voice_blueprints
        ):
            raise ValueError(
                "Duplicate voice blueprint scene numbers "
                "are not allowed."
            )

        executions: list[
            SubtitleExecution
        ] = []

        warnings: list[str] = []

        for item in timeline.ordered_items():
            editing_blueprint = (
                item.editing_blueprint
            )

            if editing_blueprint is None:
                raise ValueError(
                    "Subtitle planning requires "
                    "an editing blueprint for every scene."
                )

            subtitle_instruction = (
                editing_blueprint.subtitles
            )

            if not subtitle_instruction.enabled:
                continue

            voice_blueprint = blueprint_map.get(
                item.scene_number
            )

            if voice_blueprint is None:
                raise ValueError(
                    "Subtitle planning requires "
                    "a voice blueprint for scene "
                    f"{item.scene_number}."
                )

            scene_executions = (
                self.build_scene_subtitles(
                    item=item,
                    voice_blueprint=voice_blueprint,
                    minimum_segment_duration_seconds=(
                        minimum_segment_duration_seconds
                    ),
                    maximum_segment_duration_seconds=(
                        maximum_segment_duration_seconds
                    ),
                )
            )

            executions.extend(
                scene_executions
            )

            warnings.extend(
                warning
                for execution in scene_executions
                for warning
                in execution.warnings
            )

        plan = self._create_plan(
            timeline=timeline,
            executions=executions,
            warnings=warnings,
        )

        self.validate_plan(
            plan
        )

        if mark_ready:
            self.mark_ready(
                plan
            )

        return plan

    def build_scene_subtitles(
        self,
        *,
        item: VideoTimelineItem,
        voice_blueprint: ResolvedVoiceBlueprint,
        minimum_segment_duration_seconds: float,
        maximum_segment_duration_seconds: float,
    ) -> list[SubtitleExecution]:
        """Build subtitle segments for one timeline scene."""

        editing_blueprint = item.editing_blueprint

        if editing_blueprint is None:
            raise ValueError(
                "Scene subtitle planning requires "
                "an editing blueprint."
            )

        subtitle_instruction = (
            editing_blueprint.subtitles
        )

        if not subtitle_instruction.enabled:
            return []

        narration = (
            voice_blueprint.narration_text.strip()
        )

        if not narration:
            return []

        if (
            voice_blueprint.scene_number
            != item.scene_number
        ):
            raise ValueError(
                "Voice blueprint scene number does not "
                "match subtitle timeline scene."
            )

        chunks = self._chunk_text(
            narration,
            maximum_words=(
                subtitle_instruction
                .maximum_words_per_line
            ),
        )

        if not chunks:
            return []

        timing_duration = (
            voice_blueprint
            .estimated_speech_duration_seconds
        )

        if timing_duration <= 0.0:
            timing_duration = (
                item.duration_seconds
            )

        timing_duration = min(
            timing_duration,
            item.duration_seconds,
        )

        durations = self._allocate_durations(
            chunks=chunks,
            available_duration_seconds=(
                timing_duration
            ),
            minimum_segment_duration_seconds=(
                minimum_segment_duration_seconds
            ),
            maximum_segment_duration_seconds=(
                maximum_segment_duration_seconds
            ),
        )

        preset_id = (
            subtitle_instruction
            .preset
            .resolved_preset_id
        )

        animation_preset_id = (
            subtitle_instruction
            .animation_preset
            .resolved_preset_id
            if (
                subtitle_instruction
                .animation_preset
                is not None
            )
            else None
        )

        executions: list[
            SubtitleExecution
        ] = []

        local_start = 0.0

        for index, (
            chunk,
            duration,
        ) in enumerate(
            zip(
                chunks,
                durations,
                strict=True,
            )
        ):
            local_end = min(
                local_start + duration,
                item.duration_seconds,
            )

            actual_duration = (
                local_end - local_start
            )

            if actual_duration <= 0.0:
                continue

            warnings: list[str] = []

            if (
                voice_blueprint
                .estimated_speech_duration_seconds
                <= 0.0
            ):
                warnings.append(
                    "Subtitle timing used scene duration "
                    "because speech duration was unavailable."
                )

            if (
                subtitle_instruction
                .preset
                .used_fallback
            ):
                warnings.append(
                    "Subtitle styling uses "
                    "a fallback preset."
                )

            execution = SubtitleExecution(
                status=(
                    SubtitleExecutionStatus
                    .PLANNED
                ),
                scene_number=item.scene_number,
                segment_index=index,
                text=chunk,
                preset_id=preset_id,
                animation_preset_id=(
                    animation_preset_id
                ),
                burn_into_video=(
                    subtitle_instruction
                    .burn_into_video
                ),
                timing_source=(
                    SubtitleTimingSource
                    .ESTIMATED
                ),
                start_time_seconds=(
                    item.start_time_seconds
                    + local_start
                ),
                end_time_seconds=(
                    item.start_time_seconds
                    + local_end
                ),
                duration_seconds=(
                    actual_duration
                ),
                scene_start_time_seconds=(
                    item.start_time_seconds
                ),
                scene_end_time_seconds=(
                    item.end_time_seconds
                ),
                local_start_offset_seconds=(
                    local_start
                ),
                local_end_offset_seconds=(
                    local_end
                ),
                word_count=len(
                    chunk.split()
                ),
                metadata={
                    "timeline_item_id": str(
                        item.id
                    ),
                    "voice_blueprint_id": str(
                        voice_blueprint.id
                    ),
                    "directive_path": (
                        subtitle_instruction
                        .preset
                        .directive_path
                    ),
                    "used_fallback": (
                        subtitle_instruction
                        .preset
                        .used_fallback
                    ),
                },
                warnings=warnings,
            )

            executions.append(
                execution
            )

            local_start = local_end

        return executions

    def validate_plan(
        self,
        plan: SubtitleExecutionPlan,
    ) -> SubtitleExecutionPlan:
        """Validate subtitle timing and overlap."""

        errors: list[str] = []

        ordered = sorted(
            plan.executions,
            key=lambda execution: (
                execution.scene_number,
                execution.start_time_seconds,
                execution.segment_index,
            ),
        )

        previous_by_scene: dict[
            int,
            SubtitleExecution,
        ] = {}

        for execution in ordered:
            execution_errors: list[str] = []

            if (
                execution.end_time_seconds
                > (
                    plan.timeline_duration_seconds
                    + self.TIME_TOLERANCE_SECONDS
                )
            ):
                execution_errors.append(
                    "Subtitle ends after video timeline."
                )

            previous = previous_by_scene.get(
                execution.scene_number
            )

            if previous is not None:
                if (
                    execution.start_time_seconds
                    < (
                        previous.end_time_seconds
                        - self.TIME_TOLERANCE_SECONDS
                    )
                ):
                    execution_errors.append(
                        "Subtitle segments overlap "
                        "within the same scene."
                    )

            if execution_errors:
                execution.status = (
                    SubtitleExecutionStatus.FAILED
                )

                for message in execution_errors:
                    if message not in execution.warnings:
                        execution.warnings.append(
                            message
                        )

                    errors.append(
                        message
                    )

            elif (
                execution.status
                == SubtitleExecutionStatus.PLANNED
            ):
                execution.status = (
                    SubtitleExecutionStatus
                    .VALIDATED
                )

            previous_by_scene[
                execution.scene_number
            ] = execution

        plan.metadata[
            "validation_errors"
        ] = self._unique_text(
            errors
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

        plan.refresh_summary()

        plan.is_valid = (
            len(errors) == 0
            and plan.failed_count == 0
        )

        plan.is_render_ready = (
            plan.is_valid
            and plan.ready_execution_count
            == plan.segment_count
        )

        return plan

    def mark_ready(
        self,
        plan: SubtitleExecutionPlan,
    ) -> SubtitleExecutionPlan:
        """Mark validated subtitle segments as ready."""

        self.validate_plan(
            plan
        )

        if not plan.is_valid:
            raise ValueError(
                "Invalid subtitle execution plan "
                "cannot be marked ready."
            )

        for execution in plan.executions:
            if (
                execution.status
                == SubtitleExecutionStatus
                .VALIDATED
            ):
                execution.status = (
                    SubtitleExecutionStatus.READY
                )

        plan.refresh_summary()

        return plan

    def mark_applied(
        self,
        plan: SubtitleExecutionPlan,
        *,
        execution_id: str,
        renderer: str,
        renderer_metadata: (
            dict[str, Any] | None
        ) = None,
    ) -> SubtitleExecution:
        """Mark one subtitle segment as applied."""

        cleaned_renderer = renderer.strip()

        if not cleaned_renderer:
            raise ValueError(
                "Applied subtitle requires "
                "a renderer name."
            )

        execution = self._find_execution(
            plan=plan,
            execution_id=execution_id,
        )

        if execution.status not in {
            SubtitleExecutionStatus.READY,
            SubtitleExecutionStatus.APPLIED,
        }:
            raise ValueError(
                "Only ready subtitle executions "
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
            SubtitleExecutionStatus.APPLIED
        )

        plan.refresh_summary()

        return execution

    def mark_failed(
        self,
        plan: SubtitleExecutionPlan,
        *,
        execution_id: str,
        error_message: str,
    ) -> SubtitleExecution:
        """Mark one subtitle segment as failed."""

        cleaned = error_message.strip()

        if not cleaned:
            raise ValueError(
                "Subtitle failure message "
                "cannot be empty."
            )

        execution = self._find_execution(
            plan=plan,
            execution_id=execution_id,
        )

        execution.status = (
            SubtitleExecutionStatus.FAILED
        )

        execution.metadata[
            "failure_message"
        ] = cleaned

        warning = (
            "Subtitle execution failed: "
            f"{cleaned}"
        )

        if warning not in execution.warnings:
            execution.warnings.append(
                warning
            )

        plan.refresh_summary()

        plan.is_valid = False
        plan.is_render_ready = False

        return execution

    def summary(
        self,
        plan: SubtitleExecutionPlan,
    ) -> dict[str, Any]:
        """Return a serializable subtitle-plan summary."""

        plan.refresh_summary()

        return {
            "plan_id": str(plan.id),
            "segment_count": (
                plan.segment_count
            ),
            "scene_count": (
                plan.scene_count
            ),
            "estimated_segment_count": (
                plan.estimated_segment_count
            ),
            "precise_segment_count": (
                plan.precise_segment_count
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
        }

    @staticmethod
    def _chunk_text(
        text: str,
        *,
        maximum_words: int,
    ) -> list[str]:
        """Split narration into punctuation-aware subtitle chunks."""

        if maximum_words < 1:
            raise ValueError(
                "Maximum subtitle words must "
                "be positive."
            )

        cleaned = re.sub(
            r"\s+",
            " ",
            text.strip(),
        )

        if not cleaned:
            return []

        sentence_parts = [
            part.strip()
            for part in re.split(
                r"(?<=[.!?])\s+",
                cleaned,
            )
            if part.strip()
        ]

        chunks: list[str] = []

        for sentence in sentence_parts:
            words = sentence.split()

            while words:
                chunk_words = words[
                    :maximum_words
                ]

                chunks.append(
                    " ".join(
                        chunk_words
                    )
                )

                words = words[
                    maximum_words:
                ]

        return chunks

    @staticmethod
    def _allocate_durations(
        *,
        chunks: list[str],
        available_duration_seconds: float,
        minimum_segment_duration_seconds: float,
        maximum_segment_duration_seconds: float,
    ) -> list[float]:
        """Allocate proportional subtitle durations by word count."""

        if not chunks:
            return []

        if available_duration_seconds <= 0.0:
            raise ValueError(
                "Subtitle timing requires "
                "positive available duration."
            )

        word_counts = [
            len(chunk.split())
            for chunk in chunks
        ]

        total_words = sum(
            word_counts
        )

        if total_words <= 0:
            raise ValueError(
                "Subtitle chunks require words."
            )

        raw_durations = [
            (
                available_duration_seconds
                * word_count
                / total_words
            )
            for word_count in word_counts
        ]

        durations = [
            min(
                maximum_segment_duration_seconds,
                max(
                    minimum_segment_duration_seconds,
                    raw_duration,
                ),
            )
            for raw_duration in raw_durations
        ]

        total_allocated = sum(
            durations
        )

        if (
            total_allocated
            > available_duration_seconds
        ):
            scale = (
                available_duration_seconds
                / total_allocated
            )

            durations = [
                duration * scale
                for duration in durations
            ]

        return durations

    @staticmethod
    def _create_plan(
        *,
        timeline: VideoTimeline,
        executions: list[
            SubtitleExecution
        ],
        warnings: list[str],
    ) -> SubtitleExecutionPlan:
        """Create initial subtitle execution plan."""

        ordered = sorted(
            executions,
            key=lambda execution: (
                execution.start_time_seconds,
                execution.scene_number,
                execution.segment_index,
            ),
        )

        return SubtitleExecutionPlan(
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
            segment_count=len(
                ordered
            ),
            estimated_segment_count=sum(
                1
                for execution in ordered
                if (
                    execution.timing_source
                    == SubtitleTimingSource
                    .ESTIMATED
                )
            ),
            precise_segment_count=sum(
                1
                for execution in ordered
                if (
                    execution.timing_source
                    == SubtitleTimingSource
                    .PRECISE
                )
            ),
            ready_execution_count=0,
            is_valid=True,
            is_render_ready=False,
            warnings=(
                SubtitleExecutionService
                ._unique_text(
                    warnings
                )
            ),
        )

    @staticmethod
    def _find_execution(
        *,
        plan: SubtitleExecutionPlan,
        execution_id: str,
    ) -> SubtitleExecution:
        cleaned = execution_id.strip()

        if not cleaned:
            raise ValueError(
                "Subtitle execution ID "
                "cannot be empty."
            )

        for execution in plan.executions:
            if str(execution.id) == cleaned:
                return execution

        raise KeyError(
            "Subtitle execution was not found: "
            f"{cleaned}"
        )

    @staticmethod
    def _unique_text(
        values: list[str],
    ) -> list[str]:
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