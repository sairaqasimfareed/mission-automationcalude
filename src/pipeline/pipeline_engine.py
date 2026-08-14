from __future__ import annotations

from typing import Any

from src.models.video_job import VideoJob
from src.pipeline.pipeline_resume_plan import (
    PipelineResumePlan,
)
from src.pipeline.pipeline_runner import (
    PipelineRunner,
)
from src.pipeline.pipeline_stage import (
    PipelineStageName,
)
from src.pipeline.pipeline_state import (
    PipelineState,
)
from src.pipeline.stage_context import (
    StageContext,
)


class PipelineEngine:
    """
    Main entry point for executing a video production pipeline.

    The engine owns StageContext creation while PipelineRunner owns
    stage execution, retries, blocking behavior, and resume-stage
    selection.

    User input remains execution-scoped. The engine forwards a copied
    user-input mapping into StageContext without interpreting
    stage-specific business decisions.
    """

    def __init__(
        self,
        runner: PipelineRunner,
    ) -> None:
        self.runner = runner

    def run(
        self,
        job: VideoJob,
        *,
        dry_run: bool = True,
        resume_plan: PipelineResumePlan | None = None,
        user_input: dict[str, Any] | None = None,
        services: dict[str, Any] | None = None,
    ) -> StageContext:
        """
        Execute one pipeline run.

        A fresh PipelineState is created for the current execution.
        Historical pipeline execution state remains represented by
        PipelineCheckpoint and PipelineResumePlan.

        Domain state that belongs to VideoJob, such as persisted scene
        asset workflow state, remains attached to VideoJob.

        User input is copied into StageContext so individual pipeline
        stages can consume only the input they own.

        services carries execution-scoped, per-call collaborators (for
        example a render-progress callback) that a stage may read via
        StageContext.services - as opposed to stage-construction-time
        dependencies, which are wired through the stage factory instead.
        """

        initial_stage = (
            resume_plan.resume_stage
            if (
                resume_plan is not None
                and resume_plan.resume_enabled
                and resume_plan.resume_stage is not None
            )
            else PipelineStageName.RESEARCH
        )

        state = PipelineState(
            current_stage=(initial_stage),
        )

        context = StageContext(
            job=job,
            pipeline_state=state,
            dry_run=dry_run,
            user_input=dict(user_input or {}),
            services=dict(services or {}),
        )

        self.runner.run(
            context,
            resume_plan=resume_plan,
        )

        return context
