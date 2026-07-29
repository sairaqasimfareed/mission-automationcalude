from __future__ import annotations

from pydantic import Field

from src.models.base import MissionBaseModel
from src.pipeline.pipeline_stage import (
    PipelineStageName,
    PipelineStageStatus,
)
from src.pipeline.stage_result import StageResult


class PipelineState(MissionBaseModel):
    """Tracks the execution state of a pipeline."""

    current_stage: PipelineStageName

    overall_progress: int = 0

    stages: list[StageResult] = Field(default_factory=list)

    warnings: list[str] = Field(default_factory=list)

    errors: list[str] = Field(default_factory=list)

    @property
    def completed_stages(self) -> int:
        return sum(
            stage.status == PipelineStageStatus.COMPLETED for stage in self.stages
        )

    @property
    def failed(self) -> bool:
        return any(stage.status == PipelineStageStatus.FAILED for stage in self.stages)
