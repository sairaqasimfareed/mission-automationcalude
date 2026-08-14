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


# services is an execution-scoped bag for per-call collaborators (for
# example a render-progress callback) - run() must thread it onto the
# returned StageContext so a stage can read it via context.services.
def progress_callback(progress: object) -> None:
    return None


services_context = engine.run(
    job,
    services={"progress_callback": progress_callback},
)

assert services_context.services["progress_callback"] is progress_callback

# Omitting services must not raise and must leave the context's
# services dict empty, not None.
default_services_context = engine.run(job)

assert default_services_context.services == {}

print()

print("Pipeline Engine tests completed successfully.")
