from __future__ import annotations

from src.models.advanced_settings import (
    AdvancedSettings,
)
from src.models.video_job import VideoJob
from src.pipeline.base_stage import BasePipelineStage
from src.pipeline.pipeline_resume_plan import (
    PipelineResumePlan,
)
from src.pipeline.pipeline_runner import PipelineRunner
from src.pipeline.pipeline_stage import (
    PipelineStageName,
    PipelineStageStatus,
)
from src.pipeline.pipeline_state import PipelineState
from src.pipeline.stage_context import StageContext
from src.pipeline.stage_result import StageResult


class SyntheticResumeStage(
    BasePipelineStage
):
    """Deterministic stage used for resume execution tests."""

    def __init__(
        self,
        *,
        stage_name: PipelineStageName,
        statuses: list[
            PipelineStageStatus
        ] | None = None,
    ) -> None:
        self._stage_name = (
            stage_name
        )

        self._statuses = list(
            statuses
            or [
                PipelineStageStatus.COMPLETED,
            ]
        )

        if not self._statuses:
            raise ValueError(
                "Synthetic resume stage requires "
                "at least one result status."
            )

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

        index = min(
            self.execution_count - 1,
            len(
                self._statuses
            ) - 1,
        )

        status = (
            self._statuses[
                index
            ]
        )

        if (
            status
            == PipelineStageStatus.FAILED
        ):
            return StageResult(
                stage=self.stage_name,
                status=status,
                errors=[
                    (
                        "Synthetic resume "
                        f"failure "
                        f"{self.execution_count}."
                    ),
                ],
            )

        if (
            status
            == (
                PipelineStageStatus
                .WAITING_FOR_USER
            )
        ):
            return StageResult(
                stage=self.stage_name,
                status=status,
                warnings=[
                    "Synthetic user input required.",
                ],
            )

        return StageResult(
            stage=self.stage_name,
            status=status,
        )

    def after_execute(
        self,
        context: StageContext,
        result: StageResult,
    ) -> None:
        del context
        del result

        self.after_count += 1


def build_context() -> StageContext:
    """Build minimum valid resume execution context."""

    job = VideoJob(
        project_name=(
            "Pipeline Resume Execution Test"
        ),
        channel_name="Mission Channel",
        niche="automation",
        topic="Resume-aware pipeline runner",
    )

    return StageContext(
        job=job,
        pipeline_state=PipelineState(
            current_stage=(
                PipelineStageName.VOICE
            ),
        ),
        dry_run=True,
    )


def build_stages() -> list[
    SyntheticResumeStage
]:
    """Build the canonical resume test pipeline."""

    return [
        SyntheticResumeStage(
            stage_name=(
                PipelineStageName.VOICE
            ),
        ),
        SyntheticResumeStage(
            stage_name=(
                PipelineStageName
                .ASSET_SELECTION
            ),
        ),
        SyntheticResumeStage(
            stage_name=(
                PipelineStageName
                .VIDEO_TIMELINE
            ),
        ),
        SyntheticResumeStage(
            stage_name=(
                PipelineStageName.RENDER
            ),
        ),
    ]


def register_stages(
    runner: PipelineRunner,
    stages: list[
        SyntheticResumeStage
    ],
) -> None:
    for stage in stages:
        runner.register(
            stage
        )


def test_normal_execution_is_unchanged() -> None:
    context = build_context()

    stages = build_stages()

    runner = PipelineRunner()

    register_stages(
        runner,
        stages,
    )

    results = runner.run(
        context
    )

    assert len(
        results
    ) == 4

    assert all(
        stage.execution_count == 1
        for stage in stages
    )

    assert all(
        result.status
        == PipelineStageStatus.COMPLETED
        for result in results
    )

    assert (
        context.pipeline_state.overall_progress
        == 100
    )


def test_resume_skips_completed_stages() -> None:
    context = build_context()

    stages = build_stages()

    runner = PipelineRunner()

    register_stages(
        runner,
        stages,
    )

    plan = PipelineResumePlan(
        resume_enabled=True,
        resume_stage=(
            PipelineStageName
            .VIDEO_TIMELINE
        ),
        skipped_stages=[
            PipelineStageName.VOICE,
            (
                PipelineStageName
                .ASSET_SELECTION
            ),
        ],
        execution_stages=[
            (
                PipelineStageName
                .VIDEO_TIMELINE
            ),
            PipelineStageName.RENDER,
        ],
        checkpoint_stage=(
            PipelineStageName
            .VIDEO_TIMELINE
        ),
        resumed_from_failure=True,
    )

    results = runner.run(
        context,
        resume_plan=plan,
    )

    assert (
        stages[0].execution_count
        == 0
    )

    assert (
        stages[1].execution_count
        == 0
    )

    assert (
        stages[2].execution_count
        == 1
    )

    assert (
        stages[3].execution_count
        == 1
    )

    assert [
        result.status
        for result in results
    ] == [
        PipelineStageStatus.SKIPPED,
        PipelineStageStatus.SKIPPED,
        PipelineStageStatus.COMPLETED,
        PipelineStageStatus.COMPLETED,
    ]

    assert (
        results[0].metadata[
            "resume_skip"
        ]
        is True
    )

    assert (
        results[1].metadata[
            "resume_skip"
        ]
        is True
    )

    assert (
        context.pipeline_state.overall_progress
        == 100
    )


def test_skipped_stage_hooks_are_not_called() -> None:
    context = build_context()

    stages = build_stages()

    runner = PipelineRunner()

    register_stages(
        runner,
        stages,
    )

    plan = PipelineResumePlan(
        resume_enabled=True,
        resume_stage=(
            PipelineStageName
            .ASSET_SELECTION
        ),
        skipped_stages=[
            PipelineStageName.VOICE,
        ],
        execution_stages=[
            (
                PipelineStageName
                .ASSET_SELECTION
            ),
            (
                PipelineStageName
                .VIDEO_TIMELINE
            ),
            PipelineStageName.RENDER,
        ],
        checkpoint_stage=(
            PipelineStageName
            .ASSET_SELECTION
        ),
        resumed_from_waiting=True,
    )

    runner.run(
        context,
        resume_plan=plan,
    )

    assert (
        stages[0].before_count
        == 0
    )

    assert (
        stages[0].execution_count
        == 0
    )

    assert (
        stages[0].after_count
        == 0
    )


def test_waiting_resume_stage_blocks_again() -> None:
    context = build_context()

    voice_stage = SyntheticResumeStage(
        stage_name=(
            PipelineStageName.VOICE
        ),
    )

    asset_stage = SyntheticResumeStage(
        stage_name=(
            PipelineStageName
            .ASSET_SELECTION
        ),
        statuses=[
            (
                PipelineStageStatus
                .WAITING_FOR_USER
            ),
        ],
    )

    timeline_stage = SyntheticResumeStage(
        stage_name=(
            PipelineStageName
            .VIDEO_TIMELINE
        ),
    )

    render_stage = SyntheticResumeStage(
        stage_name=(
            PipelineStageName.RENDER
        ),
    )

    stages = [
        voice_stage,
        asset_stage,
        timeline_stage,
        render_stage,
    ]

    runner = PipelineRunner()

    register_stages(
        runner,
        stages,
    )

    plan = PipelineResumePlan(
        resume_enabled=True,
        resume_stage=(
            PipelineStageName
            .ASSET_SELECTION
        ),
        skipped_stages=[
            PipelineStageName.VOICE,
        ],
        execution_stages=[
            (
                PipelineStageName
                .ASSET_SELECTION
            ),
            (
                PipelineStageName
                .VIDEO_TIMELINE
            ),
            PipelineStageName.RENDER,
        ],
        checkpoint_stage=(
            PipelineStageName
            .ASSET_SELECTION
        ),
        resumed_from_waiting=True,
    )

    results = runner.run(
        context,
        resume_plan=plan,
    )

    assert len(
        results
    ) == 2

    assert (
        results[0].status
        == PipelineStageStatus.SKIPPED
    )

    assert (
        results[1].status
        == (
            PipelineStageStatus
            .WAITING_FOR_USER
        )
    )

    assert (
        voice_stage.execution_count
        == 0
    )

    assert (
        asset_stage.execution_count
        == 1
    )

    assert (
        timeline_stage.execution_count
        == 0
    )

    assert (
        render_stage.execution_count
        == 0
    )

    assert (
        context.pipeline_state.current_stage
        == (
            PipelineStageName
            .ASSET_SELECTION
        )
    )

    assert (
        context.pipeline_state.overall_progress
        == 50
    )


def test_resumed_failed_stage_can_retry() -> None:
    context = build_context()

    voice_stage = SyntheticResumeStage(
        stage_name=(
            PipelineStageName.VOICE
        ),
    )

    render_stage = SyntheticResumeStage(
        stage_name=(
            PipelineStageName.RENDER
        ),
        statuses=[
            PipelineStageStatus.FAILED,
            PipelineStageStatus.COMPLETED,
        ],
    )

    runner = PipelineRunner(
        advanced_settings=(
            AdvancedSettings(
                retry_failed_stages=True,
                maximum_stage_retries=2,
            )
        ),
    )

    runner.register(
        voice_stage
    )

    runner.register(
        render_stage
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

    results = runner.run(
        context,
        resume_plan=plan,
    )

    assert len(
        results
    ) == 2

    assert (
        voice_stage.execution_count
        == 0
    )

    assert (
        render_stage.execution_count
        == 2
    )

    assert (
        results[-1].status
        == PipelineStageStatus.COMPLETED
    )

    assert (
        results[-1].retry_count
        == 1
    )

    assert (
        context.job.retry_count
        == 1
    )

    assert (
        context.pipeline_state.errors
        == []
    )


def test_disabled_resume_plan_runs_full_pipeline() -> None:
    context = build_context()

    stages = build_stages()

    runner = PipelineRunner()

    register_stages(
        runner,
        stages,
    )

    plan = PipelineResumePlan(
        resume_enabled=False,
        execution_stages=[
            PipelineStageName.VOICE,
            (
                PipelineStageName
                .ASSET_SELECTION
            ),
            (
                PipelineStageName
                .VIDEO_TIMELINE
            ),
            PipelineStageName.RENDER,
        ],
    )

    results = runner.run(
        context,
        resume_plan=plan,
    )

    assert len(
        results
    ) == 4

    assert all(
        stage.execution_count == 1
        for stage in stages
    )


def test_completed_checkpoint_plan_executes_nothing() -> None:
    context = build_context()

    stages = build_stages()

    runner = PipelineRunner()

    register_stages(
        runner,
        stages,
    )

    plan = PipelineResumePlan(
        resume_enabled=False,
        execution_stages=[],
        checkpoint_stage=(
            PipelineStageName.RENDER
        ),
    )

    results = runner.run(
        context,
        resume_plan=plan,
    )

    assert results == []

    assert all(
        stage.execution_count == 0
        for stage in stages
    )

    assert (
        context.pipeline_state.overall_progress
        == 100
    )


def test_unregistered_resume_stage_is_rejected() -> None:
    context = build_context()

    runner = PipelineRunner()

    runner.register(
        SyntheticResumeStage(
            stage_name=(
                PipelineStageName.VOICE
            ),
        )
    )

    plan = PipelineResumePlan(
        resume_enabled=True,
        resume_stage=(
            PipelineStageName.SCRIPT
        ),
        execution_stages=[
            PipelineStageName.SCRIPT,
        ],
        resumed_from_failure=True,
    )

    try:
        runner.run(
            context,
            resume_plan=plan,
        )
    except ValueError as error:
        assert (
            "unregistered stage"
            in str(error)
        )
    else:
        raise AssertionError(
            "Unregistered resume stage "
            "must fail."
        )


def test_resume_execution_order_is_validated() -> None:
    context = build_context()

    voice_stage = SyntheticResumeStage(
        stage_name=(
            PipelineStageName.VOICE
        ),
    )

    render_stage = SyntheticResumeStage(
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

    plan = PipelineResumePlan(
        resume_enabled=True,
        resume_stage=(
            PipelineStageName.RENDER
        ),
        execution_stages=[
            PipelineStageName.RENDER,
            PipelineStageName.VOICE,
        ],
        resumed_from_failure=True,
    )

    try:
        runner.run(
            context,
            resume_plan=plan,
        )
    except ValueError as error:
        assert (
            "preserve registered stage order"
            in str(error)
        )
    else:
        raise AssertionError(
            "Out-of-order resume plan "
            "must fail."
        )

    assert (
        voice_stage.execution_count
        == 0
    )

    assert (
        render_stage.execution_count
        == 0
    )


def test_enabled_resume_plan_must_cover_pipeline() -> None:
    context = build_context()

    voice_stage = SyntheticResumeStage(
        stage_name=(
            PipelineStageName.VOICE
        ),
    )

    render_stage = SyntheticResumeStage(
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

    plan = PipelineResumePlan(
        resume_enabled=True,
        resume_stage=(
            PipelineStageName.RENDER
        ),
        execution_stages=[
            PipelineStageName.RENDER,
        ],
        resumed_from_failure=True,
    )

    try:
        runner.run(
            context,
            resume_plan=plan,
        )
    except ValueError as error:
        assert (
            "account for every registered stage"
            in str(error)
        )
    else:
        raise AssertionError(
            "Incomplete resume plan must fail."
        )

    assert (
        voice_stage.execution_count
        == 0
    )

    assert (
        render_stage.execution_count
        == 0
    )


def main() -> None:
    print()
    print(
        "Running Pipeline Resume "
        "Execution tests..."
    )
    print()

    test_normal_execution_is_unchanged()
    test_resume_skips_completed_stages()
    test_skipped_stage_hooks_are_not_called()
    test_waiting_resume_stage_blocks_again()
    test_resumed_failed_stage_can_retry()
    test_disabled_resume_plan_runs_full_pipeline()
    (
        test_completed_checkpoint_plan_executes_nothing()
    )
    test_unregistered_resume_stage_is_rejected()
    test_resume_execution_order_is_validated()
    test_enabled_resume_plan_must_cover_pipeline()

    print()
    print(
        "Pipeline Resume Execution tests "
        "completed successfully."
    )


if __name__ == "__main__":
    main()