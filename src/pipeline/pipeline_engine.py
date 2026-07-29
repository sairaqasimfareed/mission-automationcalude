from __future__ import annotations

from src.models.video_job import VideoJob
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
    """Main entry point for executing a video production pipeline."""

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
    ) -> StageContext:

        state = PipelineState(
            current_stage=PipelineStageName.RESEARCH,
        )

        context = StageContext(
            job=job,
            pipeline_state=state,
            dry_run=dry_run,
        )

        self.runner.run(context)

        return context
