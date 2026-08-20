from __future__ import annotations

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


class SyntheticStage(BasePipelineStage):
    """Deterministic stage used to test PipelineRunner."""

    def __init__(
        self,
        *,
        stage_name: PipelineStageName,
        status: PipelineStageStatus,
        execution_log: list[PipelineStageName],
        warnings: list[str] | None = None,
        errors: list[str] | None = None,
        reported_stage: PipelineStageName | None = None,
    ) -> None:
        self._stage_name = stage_name

        self._status = status

        self._execution_log = execution_log

        self._warnings = list(warnings or [])

        self._errors = list(errors or [])

        self._reported_stage = reported_stage

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

        self._execution_log.append(self.stage_name)

        return StageResult(
            stage=(self._reported_stage or self.stage_name),
            status=self._status,
            warnings=list(self._warnings),
            errors=list(self._errors),
        )


def build_context() -> StageContext:
    """Build a minimal valid pipeline context."""

    job = VideoJob(
        project_name="Pipeline Runner Test",
        channel_name="Mission Channel",
        niche="automation",
        topic="Pipeline runner hardening",
    )

    return StageContext(
        job=job,
        pipeline_state=PipelineState(
            current_stage=(PipelineStageName.RESEARCH),
        ),
        dry_run=True,
    )


def test_registered_stages_are_copied() -> None:
    execution_log: list[PipelineStageName] = []

    stage = SyntheticStage(
        stage_name=(PipelineStageName.RESEARCH),
        status=(PipelineStageStatus.COMPLETED),
        execution_log=execution_log,
    )

    runner = PipelineRunner()

    runner.register(stage)

    returned = runner.stages

    returned.clear()

    assert len(runner.stages) == 1


def test_completed_stages_continue() -> None:
    execution_log: list[PipelineStageName] = []

    runner = PipelineRunner()

    runner.register(
        SyntheticStage(
            stage_name=(PipelineStageName.RESEARCH),
            status=(PipelineStageStatus.COMPLETED),
            execution_log=execution_log,
        )
    )

    runner.register(
        SyntheticStage(
            stage_name=(PipelineStageName.SCRIPT),
            status=(PipelineStageStatus.COMPLETED),
            execution_log=execution_log,
        )
    )

    context = build_context()

    results = runner.run(context)

    assert len(results) == 2

    assert execution_log == [
        PipelineStageName.RESEARCH,
        PipelineStageName.SCRIPT,
    ]

    assert context.pipeline_state.overall_progress == 100


def test_failed_stage_stops_pipeline() -> None:
    execution_log: list[PipelineStageName] = []

    runner = PipelineRunner()

    runner.register(
        SyntheticStage(
            stage_name=(PipelineStageName.RESEARCH),
            status=(PipelineStageStatus.COMPLETED),
            execution_log=execution_log,
        )
    )

    runner.register(
        SyntheticStage(
            stage_name=(PipelineStageName.ASSET_SELECTION),
            status=(PipelineStageStatus.FAILED),
            execution_log=execution_log,
            errors=[
                "Synthetic asset failure.",
            ],
        )
    )

    runner.register(
        SyntheticStage(
            stage_name=(PipelineStageName.VIDEO_TIMELINE),
            status=(PipelineStageStatus.COMPLETED),
            execution_log=execution_log,
        )
    )

    context = build_context()

    results = runner.run(context)

    assert len(results) == 2

    assert execution_log == [
        PipelineStageName.RESEARCH,
        PipelineStageName.ASSET_SELECTION,
    ]

    assert context.pipeline_state.current_stage == PipelineStageName.ASSET_SELECTION

    assert context.pipeline_state.errors == [
        "Synthetic asset failure.",
    ]

    assert context.pipeline_state.overall_progress == 66


def test_waiting_for_user_stops_pipeline() -> None:
    execution_log: list[PipelineStageName] = []

    runner = PipelineRunner()

    runner.register(
        SyntheticStage(
            stage_name=(PipelineStageName.ASSET_SELECTION),
            status=(PipelineStageStatus.WAITING_FOR_USER),
            execution_log=execution_log,
            warnings=[
                "User selection required.",
            ],
        )
    )

    runner.register(
        SyntheticStage(
            stage_name=(PipelineStageName.VIDEO_TIMELINE),
            status=(PipelineStageStatus.COMPLETED),
            execution_log=execution_log,
        )
    )

    context = build_context()

    results = runner.run(context)

    assert len(results) == 1

    assert execution_log == [
        PipelineStageName.ASSET_SELECTION,
    ]

    assert results[0].status == PipelineStageStatus.WAITING_FOR_USER

    assert context.pipeline_state.current_stage == PipelineStageName.ASSET_SELECTION

    assert context.pipeline_state.warnings == [
        "User selection required.",
    ]

    assert context.pipeline_state.overall_progress == 50


def test_skipped_stage_allows_continuation() -> None:
    execution_log: list[PipelineStageName] = []

    runner = PipelineRunner()

    runner.register(
        SyntheticStage(
            stage_name=(PipelineStageName.BACKGROUND_MUSIC),
            status=(PipelineStageStatus.SKIPPED),
            execution_log=execution_log,
        )
    )

    runner.register(
        SyntheticStage(
            stage_name=(PipelineStageName.RENDER),
            status=(PipelineStageStatus.COMPLETED),
            execution_log=execution_log,
        )
    )

    context = build_context()

    results = runner.run(context)

    assert len(results) == 2

    assert execution_log == [
        PipelineStageName.BACKGROUND_MUSIC,
        PipelineStageName.RENDER,
    ]

    assert context.pipeline_state.overall_progress == 100


def test_diagnostics_are_deduplicated() -> None:
    execution_log: list[PipelineStageName] = []

    runner = PipelineRunner()

    runner.register(
        SyntheticStage(
            stage_name=(PipelineStageName.RESEARCH),
            status=(PipelineStageStatus.COMPLETED),
            execution_log=execution_log,
            warnings=[
                "Shared warning.",
            ],
        )
    )

    runner.register(
        SyntheticStage(
            stage_name=(PipelineStageName.SCRIPT),
            status=(PipelineStageStatus.FAILED),
            execution_log=execution_log,
            warnings=[
                "Shared warning.",
            ],
            errors=[
                "Shared failure.",
                "Shared failure.",
            ],
        )
    )

    context = build_context()

    runner.run(context)

    assert context.pipeline_state.warnings == [
        "Shared warning.",
    ]

    assert context.pipeline_state.errors == [
        "Shared failure.",
    ]


def test_result_stage_mismatch_is_rejected() -> None:
    execution_log: list[PipelineStageName] = []

    runner = PipelineRunner()

    runner.register(
        SyntheticStage(
            stage_name=(PipelineStageName.RESEARCH),
            reported_stage=(PipelineStageName.SCRIPT),
            status=(PipelineStageStatus.COMPLETED),
            execution_log=execution_log,
        )
    )

    context = build_context()

    try:
        runner.run(context)
    except ValueError as error:
        assert "different stage" in str(error)
    else:
        raise AssertionError("Mismatched StageResult stage " "must fail.")

    assert context.pipeline_state.stages == []


def test_empty_runner_returns_no_results() -> None:
    runner = PipelineRunner()

    context = build_context()

    results = runner.run(context)

    assert results == []

    assert context.pipeline_state.overall_progress == 0


def main() -> None:
    print()
    print("Running Pipeline Runner tests...")
    print()

    test_registered_stages_are_copied()
    test_completed_stages_continue()
    test_failed_stage_stops_pipeline()
    test_waiting_for_user_stops_pipeline()
    test_skipped_stage_allows_continuation()
    test_diagnostics_are_deduplicated()
    test_result_stage_mismatch_is_rejected()
    test_empty_runner_returns_no_results()

    print()
    print("Pipeline Runner tests " "completed successfully.")


if __name__ == "__main__":
    main()
