from __future__ import annotations

from typing import Any

from src.models.advanced_settings import (
    AdvancedSettings,
)
from src.models.video_job import VideoJob
from src.pipeline.base_stage import (
    BasePipelineStage,
)
from src.pipeline.pipeline_runner import (
    PipelineRunner,
)
from src.pipeline.pipeline_stage import (
    PipelineStageName,
    PipelineStageStatus,
)
from src.pipeline.pipeline_state import (
    PipelineState,
)
from src.pipeline.stage_context import (
    StageContext,
)
from src.pipeline.stage_result import (
    StageResult,
)


class ConsumingRetryStage(BasePipelineStage):
    """
    Synthetic stage proving one-shot user input is not reapplied
    across automatic retry attempts.

    The first execution consumes the command and fails.

    The second execution succeeds only if the same command is no
    longer available in StageContext.
    """

    USER_INPUT_KEY = "synthetic_decision"

    def __init__(self) -> None:
        self.execution_count = 0
        self.decision_apply_count = 0
        self.seen_payloads: list[Any] = []

    @property
    def stage_name(
        self,
    ) -> PipelineStageName:
        return PipelineStageName.RENDER

    def execute(
        self,
        context: StageContext,
    ) -> StageResult:
        self.execution_count += 1

        payload = context.consume_user_input(self.USER_INPUT_KEY)

        self.seen_payloads.append(payload)

        if payload is not None:
            self.decision_apply_count += 1

        if self.execution_count == 1:
            return StageResult(
                stage=self.stage_name,
                status=(PipelineStageStatus.FAILED),
                errors=[
                    "Synthetic first-attempt failure.",
                ],
            )

        return StageResult(
            stage=self.stage_name,
            status=(PipelineStageStatus.COMPLETED),
        )


class NonConsumingRetryStage(BasePipelineStage):
    """
    Control stage proving non-destructive reads remain visible across
    retry attempts.
    """

    USER_INPUT_KEY = "synthetic_decision"

    def __init__(self) -> None:
        self.execution_count = 0
        self.seen_payloads: list[Any] = []

    @property
    def stage_name(
        self,
    ) -> PipelineStageName:
        return PipelineStageName.RENDER

    def execute(
        self,
        context: StageContext,
    ) -> StageResult:
        self.execution_count += 1

        payload = context.get_user_input(self.USER_INPUT_KEY)

        self.seen_payloads.append(payload)

        if self.execution_count == 1:
            return StageResult(
                stage=self.stage_name,
                status=(PipelineStageStatus.FAILED),
                errors=[
                    "Synthetic first-attempt failure.",
                ],
            )

        return StageResult(
            stage=self.stage_name,
            status=(PipelineStageStatus.COMPLETED),
        )


def build_settings() -> AdvancedSettings:
    return AdvancedSettings(
        retry_failed_stages=True,
        maximum_stage_retries=1,
        stop_on_stage_failure=True,
    )


def build_context() -> StageContext:
    job = VideoJob(
        project_name=("Pipeline User Input Retry Guard"),
        channel_name="Mission Channel",
        niche="automation",
        topic=("Retry-safe one-shot user input"),
    )

    return StageContext(
        job=job,
        pipeline_state=(
            PipelineState(
                current_stage=(PipelineStageName.RENDER),
            )
        ),
        dry_run=True,
        user_input={
            "synthetic_decision": {
                "approved": True,
            },
            "unrelated": ("preserve-me"),
        },
    )


def test_consumed_input_is_not_reapplied_on_retry() -> None:
    context = build_context()

    stage = ConsumingRetryStage()

    runner = PipelineRunner(
        advanced_settings=(build_settings()),
    )

    runner.register(stage)

    results = runner.run(context)

    assert len(results) == 1

    result = results[0]

    assert result.status == PipelineStageStatus.COMPLETED

    assert result.retry_count == 1

    assert stage.execution_count == 2

    assert stage.decision_apply_count == 1

    assert stage.seen_payloads == [
        {
            "approved": True,
        },
        None,
    ]

    assert "synthetic_decision" not in context.user_input

    assert context.user_input["unrelated"] == "preserve-me"

    assert context.job.retry_count == 1


def test_non_consumed_input_remains_visible_on_retry() -> None:
    context = build_context()

    stage = NonConsumingRetryStage()

    runner = PipelineRunner(
        advanced_settings=(build_settings()),
    )

    runner.register(stage)

    results = runner.run(context)

    assert len(results) == 1

    result = results[0]

    assert result.status == PipelineStageStatus.COMPLETED

    assert result.retry_count == 1

    assert stage.execution_count == 2

    assert stage.seen_payloads == [
        {
            "approved": True,
        },
        {
            "approved": True,
        },
    ]

    assert context.has_user_input("synthetic_decision") is True


def test_consumed_input_stays_absent_after_retry_completion() -> None:
    context = build_context()

    stage = ConsumingRetryStage()

    runner = PipelineRunner(
        advanced_settings=(build_settings()),
    )

    runner.register(stage)

    runner.run(context)

    assert context.get_user_input("synthetic_decision") is None

    assert context.consume_user_input("synthetic_decision") is None


def main() -> None:
    print()
    print("Running Pipeline User Input " "Retry Guard tests...")
    print()

    test_consumed_input_is_not_reapplied_on_retry()
    test_non_consumed_input_remains_visible_on_retry()
    test_consumed_input_stays_absent_after_retry_completion()

    print()
    print("Pipeline User Input Retry Guard " "tests completed successfully.")


if __name__ == "__main__":
    main()
