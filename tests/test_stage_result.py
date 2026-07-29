from src.pipeline.pipeline_stage import (
    PipelineStageName,
    PipelineStageStatus,
)

from src.pipeline.stage_result import (
    StageResult,
)

result = StageResult(
    stage=PipelineStageName.RESEARCH,
    status=PipelineStageStatus.COMPLETED,
    duration_seconds=2.7,
)

print("Stage:", result.stage)
print("Status:", result.status)
print("Successful:", result.successful)

assert result.successful
assert result.progress_percent == 100
assert result.retry_count == 0

print("Stage Result tests completed successfully.")