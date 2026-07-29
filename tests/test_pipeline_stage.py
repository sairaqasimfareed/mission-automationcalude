from src.pipeline.pipeline_stage import (
    PipelineStageName,
    PipelineStageStatus,
)


print("First stage:", PipelineStageName.RESEARCH)
print("Asset stage:", PipelineStageName.ASSET_SELECTION)
print("Waiting status:", PipelineStageStatus.WAITING_FOR_USER)
print("Completed status:", PipelineStageStatus.COMPLETED)

assert PipelineStageName.RESEARCH.value == "research"
assert PipelineStageName.RENDER.value == "render"
assert PipelineStageStatus.PENDING.value == "pending"
assert (
    PipelineStageStatus.WAITING_FOR_USER.value
    == "waiting_for_user"
)

print("Pipeline Stage tests completed successfully.")