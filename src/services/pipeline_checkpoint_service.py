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
    Build serializable pipeline checkpoints from current execution state.

    This service does not persist checkpoints. Storage is a separate
    responsibility and can later be backed by files, a database, or
    another persistence provider.

    Responsibilities:
    - snapshot PipelineState;
    - derive completed/skipped/failed/waiting stages;
    - retain retry counts and diagnostics;
    - associate the checkpoint with the current VideoJob.
    """

    def create(
        self,
        *,
        job: VideoJob,
        pipeline_state: PipelineState,
        metadata: dict[str, Any] | None = None,
    ) -> PipelineCheckpoint:
        """Create a validated checkpoint from current execution state."""

        completed_stages = (
            self._stages_with_status(
                pipeline_state.stages,
                PipelineStageStatus.COMPLETED,
            )
        )

        skipped_stages = (
            self._stages_with_status(
                pipeline_state.stages,
                PipelineStageStatus.SKIPPED,
            )
        )

        failed_stage = (
            self._last_stage_with_status(
                pipeline_state.stages,
                PipelineStageStatus.FAILED,
            )
        )

        waiting_stage = (
            self._last_stage_with_status(
                pipeline_state.stages,
                PipelineStageStatus.WAITING_FOR_USER,
            )
        )

        return PipelineCheckpoint(
            job_id=job.id,
            current_stage=(
                pipeline_state.current_stage
            ),
            overall_progress=(
                pipeline_state.overall_progress
            ),
            completed_stages=completed_stages,
            skipped_stages=skipped_stages,
            failed_stage=failed_stage,
            waiting_stage=waiting_stage,
            stage_results=list(
                pipeline_state.stages
            ),
            total_retry_count=(
                job.retry_count
            ),
            warnings=list(
                pipeline_state.warnings
            ),
            errors=list(
                pipeline_state.errors
            ),
            metadata=dict(
                metadata
                or {}
            ),
        )

    @staticmethod
    def _stages_with_status(
        results: list[StageResult],
        status: PipelineStageStatus,
    ) -> list[PipelineStageName]:
        """Return unique stages matching one status."""

        stages: list[
            PipelineStageName
        ] = []

        for result in results:
            if (
                result.status
                != status
            ):
                continue

            if (
                result.stage
                not in stages
            ):
                stages.append(
                    result.stage
                )

        return stages

    @staticmethod
    def _last_stage_with_status(
        results: list[StageResult],
        status: PipelineStageStatus,
    ) -> PipelineStageName | None:
        """
        Return the most recent stage matching one status.

        A checkpoint represents the current execution boundary, so the
        latest matching stage is authoritative.
        """

        for result in reversed(
            results
        ):
            if (
                result.status
                == status
            ):
                return result.stage

        return None