from src.models.video_job import VideoJob
from src.pipeline.base_stage import (
    BasePipelineStage,
)
from src.pipeline.pipeline_engine import (
    PipelineEngine,
)
from src.pipeline.pipeline_runner import (
    PipelineRunner,
)
from src.pipeline.pipeline_stage import (
    PipelineStageName,
    PipelineStageStatus,
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
        print("Research executed")

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
        print("Script executed")

        return StageResult(
            stage=self.stage_name,
            status=PipelineStageStatus.COMPLETED,
        )


runner = PipelineRunner()

runner.register(
    ResearchStage(),
)

runner.register(
    ScriptStage(),
)

engine = PipelineEngine(
    runner,
)

job = VideoJob(
    project_name="Mission",
    channel_name="Demo",
    niche="History",
    topic="Ancient Rome",
)

context = engine.run(
    job,
)

print()

print(
    "Current Stage:",
    context.pipeline_state.current_stage,
)

print(
    "Completed:",
    context.pipeline_state.completed_stages,
)

print(
    "Overall Progress:",
    context.pipeline_state.overall_progress,
)

assert context.pipeline_state.completed_stages == 2

assert context.pipeline_state.overall_progress == 100

print()

print("Pipeline Engine tests completed successfully.")
