from __future__ import annotations

from src.models.advanced_settings import (
    AdvancedSettings,
)
from src.models.video_job import VideoJob
from src.pipeline.base_stage import BasePipelineStage
from src.pipeline.pipeline_checkpoint import (
    PipelineCheckpoint,
)
from src.pipeline.pipeline_resume_plan import (
    PipelineResumePlan,
)
from src.pipeline.pipeline_stage import (
    PipelineStageName,
)


class PipelineResumePlannerService:
    """
    Build deterministic pipeline resume plans.

    This service performs planning only. It does not execute stages or
    mutate the VideoJob, checkpoint, or PipelineRunner.
    """

    def create_plan(
        self,
        *,
        job: VideoJob,
        checkpoint: PipelineCheckpoint,
        stages: list[BasePipelineStage],
        settings: AdvancedSettings,
    ) -> PipelineResumePlan:
        """Create a validated execution plan from one checkpoint."""

        stage_names = [
            stage.stage_name
            for stage in stages
        ]

        if not stage_names:
            raise ValueError(
                "Resume planning requires at least "
                "one registered pipeline stage."
            )

        self._validate_unique_stages(
            stage_names
        )

        if (
            checkpoint.job_id
            != job.id
        ):
            raise ValueError(
                "Pipeline checkpoint does not belong "
                "to the supplied VideoJob."
            )

        self._validate_checkpoint_stages(
            checkpoint=checkpoint,
            registered_stages=stage_names,
        )

        if not settings.resume_previous_pipeline:
            return PipelineResumePlan(
                resume_enabled=False,
                execution_stages=list(
                    stage_names
                ),
            )

        if not checkpoint.resumable:
            return PipelineResumePlan(
                resume_enabled=False,
                execution_stages=[],
                checkpoint_stage=(
                    checkpoint.current_stage
                ),
            )

        resume_stage = (
            checkpoint.failed_stage
            or checkpoint.waiting_stage
        )

        if resume_stage is None:
            raise ValueError(
                "Resumable checkpoint does not "
                "define a resume stage."
            )

        resume_index = (
            stage_names.index(
                resume_stage
            )
        )

        if settings.skip_completed_stages:
            skipped_stages = [
                stage
                for stage in stage_names[
                    :resume_index
                ]
                if stage
                in checkpoint.completed_stages
            ]

            execution_stages = [
                stage
                for stage in stage_names
                if stage
                not in skipped_stages
            ]

        else:
            skipped_stages = []

            execution_stages = list(
                stage_names
            )

            resume_stage = (
                execution_stages[
                    0
                ]
            )

        return PipelineResumePlan(
            resume_enabled=True,
            resume_stage=resume_stage,
            skipped_stages=(
                skipped_stages
            ),
            execution_stages=(
                execution_stages
            ),
            checkpoint_stage=(
                checkpoint.current_stage
            ),
            resumed_from_failure=(
                checkpoint.failed_stage
                is not None
            ),
            resumed_from_waiting=(
                checkpoint.waiting_stage
                is not None
            ),
        )

    @staticmethod
    def _validate_unique_stages(
        stages: list[
            PipelineStageName
        ],
    ) -> None:
        """Reject duplicate registered stage identifiers."""

        if (
            len(stages)
            != len(
                set(stages)
            )
        ):
            raise ValueError(
                "Resume planning cannot use "
                "duplicate pipeline stages."
            )

    @staticmethod
    def _validate_checkpoint_stages(
        *,
        checkpoint: PipelineCheckpoint,
        registered_stages: list[
            PipelineStageName
        ],
    ) -> None:
        """
        Ensure checkpoint references only stages registered for the
        current orchestration run.
        """

        referenced: set[
            PipelineStageName
        ] = {
            checkpoint.current_stage,
            *checkpoint.completed_stages,
            *checkpoint.skipped_stages,
        }

        if (
            checkpoint.failed_stage
            is not None
        ):
            referenced.add(
                checkpoint.failed_stage
            )

        if (
            checkpoint.waiting_stage
            is not None
        ):
            referenced.add(
                checkpoint.waiting_stage
            )

        registered = set(
            registered_stages
        )

        unknown = sorted(
            (
                stage.value
                for stage in (
                    referenced
                    - registered
                )
            )
        )

        if unknown:
            raise ValueError(
                "Pipeline checkpoint references "
                "unregistered stage(s): "
                + ", ".join(
                    unknown
                )
                + "."
            )