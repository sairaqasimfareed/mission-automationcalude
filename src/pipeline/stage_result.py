from __future__ import annotations

from pydantic import Field

from src.models.base import MissionBaseModel
from src.pipeline.pipeline_stage import (
    PipelineStageName,
    PipelineStageStatus,
)


class StageResult(MissionBaseModel):
    """Result returned after executing a pipeline stage."""

    stage: PipelineStageName

    status: PipelineStageStatus

    duration_seconds: float = 0.0

    retry_count: int = 0

    progress_percent: int = 100

    warnings: list[str] = Field(default_factory=list)

    errors: list[str] = Field(default_factory=list)

    metadata: dict = Field(default_factory=dict)

    @property
    def successful(self) -> bool:
        return self.status == PipelineStageStatus.COMPLETED
