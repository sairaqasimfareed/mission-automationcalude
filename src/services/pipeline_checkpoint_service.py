from __future__ import annotations

from typing import Any

from src.models.video_job import VideoJob
from src.pipeline.pipeline_checkpoint import (
    PipelineCheckpoint,
)
from src.pipeline.pipeline_stage import (
    PipelineStageName,
    PipelineStageStatus,
)
from src.pipeline.pipeline_state import PipelineState
from src.pipeline.stage_result import StageResult


class PipelineCheckpointService:
    """
    Build serializable pipeline checkpoints from execution state.

    The service supports both fresh snapshots and history-preserving
    snapshots created after resumed execution.

    Responsibilities:
    - snapshot current PipelineState;
    - preserve historical completed/skipped stages across resume runs;
    - retain historical StageResult records;
    - derive the current failed/waiting execution boundary;
    - retain retry counts and diagnostics;
    - associate the checkpoint with the current VideoJob.

    Persistence remains the responsibility of
    PipelineCheckpointStorageService.
    """

    def create(
        self,
        *,
        job: VideoJob,
        pipeline_state: PipelineState,
        metadata: dict[str, Any] | None = None,
        previous_checkpoint: PipelineCheckpoint | None = None,
    ) -> PipelineCheckpoint:
        """
        Create a validated checkpoint from current execution state.

        When previous_checkpoint is supplied, historical execution state
        is merged with the current run.

        Current execution is authoritative:
        - COMPLETED promotes a stage to completed;
        - SKIPPED preserves historical completion when that stage had
          already completed before resume;
        - FAILED or WAITING_FOR_USER removes any older completed/skipped
          classification for the re-executed stage.
        """

        if previous_checkpoint is not None and previous_checkpoint.job_id != job.id:
            raise ValueError(
                "Previous pipeline checkpoint does "
                "not belong to the supplied VideoJob."
            )

        completed_stages = self._initial_stage_list(
            previous_checkpoint,
            completed=True,
        )

        skipped_stages = self._initial_stage_list(
            previous_checkpoint,
            completed=False,
        )

        self._apply_current_results(
            results=(pipeline_state.stages),
            completed_stages=(completed_stages),
            skipped_stages=(skipped_stages),
        )

        failed_stage = self._last_stage_with_status(
            pipeline_state.stages,
            PipelineStageStatus.FAILED,
        )

        waiting_stage = self._last_stage_with_status(
            pipeline_state.stages,
            (PipelineStageStatus.WAITING_FOR_USER),
        )

        stage_results = self._merge_stage_results(
            previous_checkpoint=(previous_checkpoint),
            current_results=(pipeline_state.stages),
        )

        warnings = self._merge_messages(
            (previous_checkpoint.warnings if previous_checkpoint is not None else []),
            pipeline_state.warnings,
        )

        errors = self._merge_messages(
            (previous_checkpoint.errors if previous_checkpoint is not None else []),
            pipeline_state.errors,
        )

        return PipelineCheckpoint(
            job_id=job.id,
            current_stage=(pipeline_state.current_stage),
            overall_progress=(pipeline_state.overall_progress),
            completed_stages=(completed_stages),
            skipped_stages=(skipped_stages),
            failed_stage=failed_stage,
            waiting_stage=waiting_stage,
            stage_results=stage_results,
            total_retry_count=(job.retry_count),
            warnings=warnings,
            errors=errors,
            metadata=dict(metadata or {}),
        )

    @staticmethod
    def _initial_stage_list(
        checkpoint: PipelineCheckpoint | None,
        *,
        completed: bool,
    ) -> list[PipelineStageName]:
        """Return a copied historical stage classification."""

        if checkpoint is None:
            return []

        values = checkpoint.completed_stages if completed else checkpoint.skipped_stages

        return list(values)

    @classmethod
    def _apply_current_results(
        cls,
        *,
        results: list[StageResult],
        completed_stages: list[PipelineStageName],
        skipped_stages: list[PipelineStageName],
    ) -> None:
        """
        Apply current execution results over historical classifications.

        A synthetic resume skip must not erase an earlier successful
        completion.
        """

        for result in results:
            stage = result.stage

            if result.status == PipelineStageStatus.COMPLETED:
                cls._append_stage_unique(
                    completed_stages,
                    stage,
                )

                cls._remove_stage(
                    skipped_stages,
                    stage,
                )

                continue

            if result.status == PipelineStageStatus.SKIPPED:
                if stage not in completed_stages:
                    cls._append_stage_unique(
                        skipped_stages,
                        stage,
                    )

                continue

            if result.status in {
                PipelineStageStatus.FAILED,
                (PipelineStageStatus.WAITING_FOR_USER),
            }:
                cls._remove_stage(
                    completed_stages,
                    stage,
                )

                cls._remove_stage(
                    skipped_stages,
                    stage,
                )

    @staticmethod
    def _merge_stage_results(
        *,
        previous_checkpoint: PipelineCheckpoint | None,
        current_results: list[StageResult],
    ) -> list[StageResult]:
        """
        Preserve historical results and append current execution results.

        Multiple results for one stage are intentional. They record the
        execution history, while checkpoint failed/waiting boundaries
        are determined from the current run.
        """

        merged: list[StageResult] = []

        if previous_checkpoint is not None:
            merged.extend(previous_checkpoint.stage_results)

        merged.extend(current_results)

        return merged

    @staticmethod
    def _merge_messages(
        historical: list[str],
        current: list[str],
    ) -> list[str]:
        """Merge diagnostics while preserving stable order."""

        merged: list[str] = []

        for value in [
            *historical,
            *current,
        ]:
            cleaned = value.strip()

            if cleaned and cleaned not in merged:
                merged.append(cleaned)

        return merged

    @staticmethod
    def _append_stage_unique(
        stages: list[PipelineStageName],
        stage: PipelineStageName,
    ) -> None:
        """Append one stage exactly once."""

        if stage not in stages:
            stages.append(stage)

    @staticmethod
    def _remove_stage(
        stages: list[PipelineStageName],
        stage: PipelineStageName,
    ) -> None:
        """Remove one stage classification when present."""

        while stage in stages:
            stages.remove(stage)

    @staticmethod
    def _last_stage_with_status(
        results: list[StageResult],
        status: PipelineStageStatus,
    ) -> PipelineStageName | None:
        """Return the most recent current-run stage with one status."""

        for result in reversed(results):
            if result.status == status:
                return result.stage

        return None
