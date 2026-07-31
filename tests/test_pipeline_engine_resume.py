from __future__ import annotations

from src.models.video_job import VideoJob
from src.pipeline.base_stage import BasePipelineStage
from src.pipeline.pipeline_engine import (
    PipelineEngine,
)
from src.pipeline.pipeline_resume_plan import (
    PipelineResumePlan,
)
from src.pipeline.pipeline_runner import (
    PipelineRunner,
)
from src.pipeline.pipeline_stage import (
    PipelineStageName,
    PipelineStageStatus,
)
from src.pipeline.stage_context import (
    StageContext,
)
from src.pipeline.stage_result import (
    StageResult,
)


class SyntheticStage(
    BasePipelineStage
):
    """Deterministic stage used by PipelineEngine resume tests."""

    def __init__(
        self,
        *,
        stage_name: PipelineStageName,
    ) -> None:
        self._stage_name = stage_name
        self.execution_count = 0

    @property
    def stage_name(
        self,
    ) -> PipelineStageName:
        return self._stage_name

    def execute(
        self,
        context: StageContext,
    ) -> StageResult:
        del context

        self.execution_count += 1

        return StageResult(
            stage=self.stage_name,
            status=(
                PipelineStageStatus.COMPLETED
            ),
        )


def build_job() -> VideoJob:
    return VideoJob(
        project_name="Pipeline Engine Resume Test",
        channel_name="Mission Channel",
        niche="automation",
        topic="Pipeline engine resume support",
    )


def test_normal_execution_preserves_behavior() -> None:
    voice_stage = SyntheticStage(
        stage_name=(
            PipelineStageName.VOICE
        ),
    )

    runner = PipelineRunner()

    runner.register(
        voice_stage
    )

    engine = PipelineEngine(
        runner
    )

    context = engine.run(
        build_job(),
        dry_run=True,
    )

    assert (
        voice_stage.execution_count
        == 1
    )

    assert (
        context.pipeline_state.current_stage
        == PipelineStageName.VOICE
    )

    assert (
        context.pipeline_state.overall_progress
        == 100
    )


def test_resume_plan_is_forwarded_to_runner() -> None:
    voice_stage = SyntheticStage(
        stage_name=(
            PipelineStageName.VOICE
        ),
    )

    render_stage = SyntheticStage(
        stage_name=(
            PipelineStageName.RENDER
        ),
    )

    runner = PipelineRunner()

    runner.register(
        voice_stage
    )

    runner.register(
        render_stage
    )

    engine = PipelineEngine(
        runner
    )

    plan = PipelineResumePlan(
        resume_enabled=True,
        resume_stage=(
            PipelineStageName.RENDER
        ),
        skipped_stages=[
            PipelineStageName.VOICE,
        ],
        execution_stages=[
            PipelineStageName.RENDER,
        ],
        checkpoint_stage=(
            PipelineStageName.RENDER
        ),
        resumed_from_failure=True,
    )

    context = engine.run(
        build_job(),
        dry_run=True,
        resume_plan=plan,
    )

    assert (
        voice_stage.execution_count
        == 0
    )

    assert (
        render_stage.execution_count
        == 1
    )

    assert (
        len(
            context.pipeline_state.stages
        )
        == 2
    )

    assert (
        context.pipeline_state.stages[0].status
        == PipelineStageStatus.SKIPPED
    )

    assert (
        context.pipeline_state.stages[1].status
        == PipelineStageStatus.COMPLETED
    )

    assert (
        context.pipeline_state.current_stage
        == PipelineStageName.RENDER
    )

    assert (
        context.pipeline_state.overall_progress
        == 100
    )


def test_completed_checkpoint_plan_executes_nothing() -> None:
    stage = SyntheticStage(
        stage_name=(
            PipelineStageName.RENDER
        ),
    )

    runner = PipelineRunner()

    runner.register(
        stage
    )

    engine = PipelineEngine(
        runner
    )

    plan = PipelineResumePlan(
        resume_enabled=False,
        execution_stages=[],
        checkpoint_stage=(
            PipelineStageName.RENDER
        ),
    )

    context = engine.run(
        build_job(),
        resume_plan=plan,
    )

    assert (
        stage.execution_count
        == 0
    )

    assert (
        context.pipeline_state.stages
        == []
    )

    assert (
        context.pipeline_state.overall_progress
        == 100
    )


def main() -> None:
    print()
    print(
        "Running Pipeline Engine Resume tests..."
    )
    print()

    test_normal_execution_preserves_behavior()
    test_resume_plan_is_forwarded_to_runner()
    test_completed_checkpoint_plan_executes_nothing()

    print()
    print(
        "Pipeline Engine Resume tests "
        "completed successfully."
    )


if __name__ == "__main__":
    main()