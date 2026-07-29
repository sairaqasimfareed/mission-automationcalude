from src.pipeline.pipeline_stage import (
    PipelineStageName,
    PipelineStageStatus,
)

from src.pipeline.pipeline_state import PipelineState

from src.pipeline.stage_result import StageResult


state = PipelineState(
    current_stage=PipelineStageName.SCRIPT,
)

state.stages.append(
    StageResult(
        stage=PipelineStageName.RESEARCH,
        status=PipelineStageStatus.COMPLETED,
    )
)

state.stages.append(
    StageResult(
        stage=PipelineStageName.SCRIPT,
        status=PipelineStageStatus.RUNNING,
    )
)

print("Current:", state.current_stage)
print("Completed:", state.completed_stages)
print("Failed:", state.failed)

assert state.completed_stages == 1
assert state.failed is False

print("Pipeline State tests completed successfully.")