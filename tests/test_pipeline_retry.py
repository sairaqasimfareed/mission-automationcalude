from __future__ import annotations

from src.models.advanced_settings import (
    AdvancedSettings,
)
from src.models.video_job import VideoJob
from src.pipeline.base_stage import BasePipelineStage
from src.pipeline.pipeline_runner import PipelineRunner
from src.pipeline.pipeline_stage import (
    PipelineStageName,
    PipelineStageStatus,
)
from src.pipeline.pipeline_state import PipelineState
from src.pipeline.stage_context import StageContext
from src.pipeline.stage_result import StageResult


class RetrySyntheticStage(BasePipelineStage):
    """Deterministic stage with configurable failure count."""

    def __init__(
        self,
        *,
        stage_name: PipelineStageName,
        failures_before_success: int,
    ) -> None:
        self._stage_name = stage_name

        self._failures_before_success = failures_before_success

        self.execution_count = 0
        self.before_count = 0
        self.after_count = 0

    @property
    def stage_name(
        self,
    ) -> PipelineStageName:
        return self._stage_name

    def before_execute(
        self,
        context: StageContext,
    ) -> None:
        del context

        self.before_count += 1

    def execute(
        self,
        context: StageContext,
    ) -> StageResult:
        del context

        self.execution_count += 1

        if self.execution_count <= self._failures_before_success:
            return StageResult(
                stage=self.stage_name,
                status=(PipelineStageStatus.FAILED),
                errors=[
                    ("Synthetic failure " f"{self.execution_count}."),
                ],
            )

        return StageResult(
            stage=self.stage_name,
            status=(PipelineStageStatus.COMPLETED),
        )

    def after_execute(
        self,
        context: StageContext,
        result: StageResult,
    ) -> None:
        del context
        del result

        self.after_count += 1


class WaitingSyntheticStage(BasePipelineStage):
    """Stage that requires external user input."""

    def __init__(
        self,
    ) -> None:
        self.execution_count = 0

    @property
    def stage_name(
        self,
    ) -> PipelineStageName:
        return PipelineStageName.ASSET_SELECTION

    def execute(
        self,
        context: StageContext,
    ) -> StageResult:
        del context

        self.execution_count += 1

        return StageResult(
            stage=self.stage_name,
            status=(PipelineStageStatus.WAITING_FOR_USER),
        )


def build_context() -> StageContext:
    """Build minimum valid retry test context."""

    job = VideoJob(
        project_name="Pipeline Retry Test",
        channel_name="Mission Channel",
        niche="automation",
        topic="Pipeline retry behavior",
    )

    return StageContext(
        job=job,
        pipeline_state=PipelineState(
            current_stage=(PipelineStageName.RESEARCH),
        ),
        dry_run=True,
    )


def build_retry_settings(
    *,
    maximum_retries: int,
    stop_on_failure: bool = True,
) -> AdvancedSettings:
    """Build valid retry-enabled AdvancedSettings."""

    return AdvancedSettings(
        retry_failed_stages=True,
        maximum_stage_retries=(maximum_retries),
        stop_on_stage_failure=(stop_on_failure),
        allow_partial_output=(not stop_on_failure),
    )


def test_no_settings_preserves_no_retry_behavior() -> None:
    context = build_context()

    stage = RetrySyntheticStage(
        stage_name=PipelineStageName.VOICE,
        failures_before_success=1,
    )

    runner = PipelineRunner()

    runner.register(stage)

    results = runner.run(context)

    assert stage.execution_count == 1

    assert len(results) == 1

    assert results[0].status == PipelineStageStatus.FAILED

    assert results[0].retry_count == 0

    assert context.job.retry_count == 0


def test_failed_stage_retries_and_recovers() -> None:
    context = build_context()

    stage = RetrySyntheticStage(
        stage_name=PipelineStageName.VOICE,
        failures_before_success=1,
    )

    runner = PipelineRunner(
        advanced_settings=(build_retry_settings(maximum_retries=3)),
    )

    runner.register(stage)

    results = runner.run(context)

    assert stage.execution_count == 2

    assert results[0].status == PipelineStageStatus.COMPLETED

    assert results[0].retry_count == 1

    assert results[0].attempted_execution_count == 2

    assert context.job.retry_count == 1

    assert context.pipeline_state.errors == []


def test_multiple_retries_are_counted() -> None:
    context = build_context()

    stage = RetrySyntheticStage(
        stage_name=PipelineStageName.RENDER,
        failures_before_success=2,
    )

    runner = PipelineRunner(
        advanced_settings=(build_retry_settings(maximum_retries=3)),
    )

    runner.register(stage)

    results = runner.run(context)

    assert stage.execution_count == 3

    assert results[0].status == PipelineStageStatus.COMPLETED

    assert results[0].retry_count == 2

    assert context.job.retry_count == 2


def test_retry_limit_is_enforced() -> None:
    context = build_context()

    stage = RetrySyntheticStage(
        stage_name=PipelineStageName.RENDER,
        failures_before_success=10,
    )

    runner = PipelineRunner(
        advanced_settings=(build_retry_settings(maximum_retries=2)),
    )

    runner.register(stage)

    results = runner.run(context)

    assert stage.execution_count == 3

    assert results[0].status == PipelineStageStatus.FAILED

    assert results[0].retry_count == 2

    assert context.job.retry_count == 2

    assert context.pipeline_state.errors == [
        "Synthetic failure 3.",
    ]


def test_retry_disabled_does_not_retry() -> None:
    context = build_context()

    stage = RetrySyntheticStage(
        stage_name=PipelineStageName.VOICE,
        failures_before_success=1,
    )

    settings = AdvancedSettings(
        retry_failed_stages=False,
        maximum_stage_retries=0,
    )

    runner = PipelineRunner(
        advanced_settings=settings,
    )

    runner.register(stage)

    results = runner.run(context)

    assert stage.execution_count == 1

    assert results[0].retry_count == 0

    assert context.job.retry_count == 0


def test_waiting_for_user_is_never_retried() -> None:
    context = build_context()

    stage = WaitingSyntheticStage()

    runner = PipelineRunner(
        advanced_settings=(build_retry_settings(maximum_retries=3)),
    )

    runner.register(stage)

    results = runner.run(context)

    assert stage.execution_count == 1

    assert results[0].status == (PipelineStageStatus.WAITING_FOR_USER)

    assert results[0].retry_count == 0

    assert context.job.retry_count == 0


def test_hooks_execute_for_every_attempt() -> None:
    context = build_context()

    stage = RetrySyntheticStage(
        stage_name=PipelineStageName.VOICE,
        failures_before_success=2,
    )

    runner = PipelineRunner(
        advanced_settings=(build_retry_settings(maximum_retries=3)),
    )

    runner.register(stage)

    runner.run(context)

    assert stage.execution_count == 3
    assert stage.before_count == 3
    assert stage.after_count == 3


def test_exhausted_failure_blocks_by_default() -> None:
    context = build_context()

    failed_stage = RetrySyntheticStage(
        stage_name=PipelineStageName.VOICE,
        failures_before_success=10,
    )

    downstream_stage = RetrySyntheticStage(
        stage_name=PipelineStageName.RENDER,
        failures_before_success=0,
    )

    runner = PipelineRunner(
        advanced_settings=(
            build_retry_settings(
                maximum_retries=1,
                stop_on_failure=True,
            )
        ),
    )

    runner.register(failed_stage)

    runner.register(downstream_stage)

    results = runner.run(context)

    assert len(results) == 1

    assert failed_stage.execution_count == 2

    assert downstream_stage.execution_count == 0


def test_partial_output_allows_continuation() -> None:
    context = build_context()

    failed_stage = RetrySyntheticStage(
        stage_name=PipelineStageName.VOICE,
        failures_before_success=10,
    )

    downstream_stage = RetrySyntheticStage(
        stage_name=PipelineStageName.RENDER,
        failures_before_success=0,
    )

    runner = PipelineRunner(
        advanced_settings=(
            build_retry_settings(
                maximum_retries=1,
                stop_on_failure=False,
            )
        ),
    )

    runner.register(failed_stage)

    runner.register(downstream_stage)

    results = runner.run(context)

    assert len(results) == 2

    assert results[0].status == PipelineStageStatus.FAILED

    assert results[1].status == PipelineStageStatus.COMPLETED

    assert downstream_stage.execution_count == 1


def test_job_retry_count_accumulates_across_stages() -> None:
    context = build_context()

    first_stage = RetrySyntheticStage(
        stage_name=PipelineStageName.VOICE,
        failures_before_success=1,
    )

    second_stage = RetrySyntheticStage(
        stage_name=PipelineStageName.RENDER,
        failures_before_success=2,
    )

    runner = PipelineRunner(
        advanced_settings=(build_retry_settings(maximum_retries=3)),
    )

    runner.register(first_stage)

    runner.register(second_stage)

    results = runner.run(context)

    assert len(results) == 2

    assert results[0].retry_count == 1

    assert results[1].retry_count == 2

    assert context.job.retry_count == 3


def main() -> None:
    print()
    print("Running Pipeline Retry tests...")
    print()

    (test_no_settings_preserves_no_retry_behavior())
    (test_failed_stage_retries_and_recovers())
    test_multiple_retries_are_counted()
    test_retry_limit_is_enforced()
    test_retry_disabled_does_not_retry()
    test_waiting_for_user_is_never_retried()
    test_hooks_execute_for_every_attempt()
    test_exhausted_failure_blocks_by_default()
    test_partial_output_allows_continuation()
    (test_job_retry_count_accumulates_across_stages())

    print()
    print("Pipeline Retry tests " "completed successfully.")


if __name__ == "__main__":
    main()
