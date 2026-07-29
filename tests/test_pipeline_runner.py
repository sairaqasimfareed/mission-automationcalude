from src.models.video_job import VideoJob

from src.pipeline.base_stage import (
    BasePipelineStage,
)

from src.pipeline.pipeline_runner import (
    PipelineRunner,
)

from src.pipeline.pipeline_stage import (
    PipelineStageName,
    PipelineStageStatus,
)

from src.pipeline.pipeline_state import (
    PipelineState,
)

from src.pipeline.stage_context import (
    StageContext,
)

from src.pipeline.stage_result import (
    StageResult,
)


class ResearchStage(
    BasePipelineStage,
):

    @property
    def stage_name(self):
        return PipelineStageName.RESEARCH

    def execute(
        self,
        context,
    ):
        print("Running Research")

        return StageResult(
            stage=self.stage_name,
            status=PipelineStageStatus.COMPLETED,
        )


class ScriptStage(
    BasePipelineStage,
):

    @property
    def stage_name(self):
        return PipelineStageName.SCRIPT

    def execute(
        self,
        context,
    ):
        print("Running Script")

        return StageResult(
            stage=self.stage_name,
            status=PipelineStageStatus.COMPLETED,
        )


job = VideoJob(
    project_name="Mission",
    channel_name="Demo",
    niche="History",
    topic="Ancient Rome",
)

state = PipelineState(
    current_stage=PipelineStageName.RESEARCH,
)

context = StageContext(
    job=job,
    pipeline_state=state,
)

runner = PipelineRunner()

runner.register(
    ResearchStage(),
)

runner.register(
    ScriptStage(),
)

results = runner.run(
    context,
)

print()

print(
    "Completed:",
    len(results),
)

print(
    "Overall Progress:",
    context.pipeline_state.overall_progress,
)

assert len(results) == 2

assert (
    context.pipeline_state.overall_progress
    == 100
)

print()

print(
    "Pipeline Runner tests completed successfully."
)