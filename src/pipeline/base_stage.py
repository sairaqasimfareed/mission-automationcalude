from __future__ import annotations

from abc import ABC, abstractmethod

from src.pipeline.stage_context import StageContext
from src.pipeline.stage_result import StageResult
from src.pipeline.pipeline_stage import (
    PipelineStageName,
)


class BasePipelineStage(ABC):
    """Base class for all pipeline stages."""

    @property
    @abstractmethod
    def stage_name(self) -> PipelineStageName:
        """Unique stage identifier."""
        raise NotImplementedError

    @abstractmethod
    def execute(
        self,
        context: StageContext,
    ) -> StageResult:
        """Execute the stage."""
        raise NotImplementedError

    def before_execute(
        self,
        context: StageContext,
    ) -> None:
        """Optional hook executed before the stage."""
        return None

    def after_execute(
        self,
        context: StageContext,
        result: StageResult,
    ) -> None:
        """Optional hook executed after the stage."""
        return None