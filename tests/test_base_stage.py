from src.models.video_job import VideoJob
from src.pipeline.base_stage import BasePipelineStage
from src.pipeline.pipeline_stage import (
    PipelineStageName,
    PipelineStageStatus,
)
from src.pipeline.pipeline_state import PipelineState
from src.pipeline.stage_context import StageContext
from src.pipeline.stage_result import StageResult


class DummyStage(BasePipelineStage):

    @property
    def stage_name(self):
        return PipelineStageName.RESEARCH

    def execute(
        self,
        context: StageContext,
    ):
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

stage = DummyStage()

stage.before_execute(context)

result = stage.execute(context)

stage.after_execute(context, result)

print("Stage:", result.stage)
print("Status:", result.status)

assert result.successful

print("Base Stage tests completed successfully.")
