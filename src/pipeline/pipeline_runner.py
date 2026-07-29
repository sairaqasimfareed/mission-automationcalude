from __future__ import annotations

from src.pipeline.base_stage import BasePipelineStage
from src.pipeline.stage_context import StageContext
from src.pipeline.stage_result import StageResult


class PipelineRunner:
    """Executes registered pipeline stages sequentially."""

    def __init__(self) -> None:
        self._stages: list[BasePipelineStage] = []

    def register(
        self,
        stage: BasePipelineStage,
    ) -> None:
        self._stages.append(stage)

    @property
    def stages(self) -> list[BasePipelineStage]:
        return self._stages.copy()

    def run(
        self,
        context: StageContext,
    ) -> list[StageResult]:

        results: list[StageResult] = []

        total = len(self._stages)

        for index, stage in enumerate(
            self._stages,
            start=1,
        ):
            context.pipeline_state.current_stage = (
                stage.stage_name
            )

            stage.before_execute(context)

            result = stage.execute(context)

            stage.after_execute(
                context,
                result,
            )

            context.pipeline_state.stages.append(
                result,
            )

            context.pipeline_state.overall_progress = int(
                index * 100 / total
            )

            results.append(result)

        return results