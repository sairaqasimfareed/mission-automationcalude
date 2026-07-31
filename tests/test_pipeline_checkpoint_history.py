from __future__ import annotations

from src.models.video_job import VideoJob
from src.pipeline.pipeline_checkpoint import (
    PipelineCheckpoint,
)
from src.pipeline.pipeline_stage import (
    PipelineStageName,
    PipelineStageStatus,
)
from src.pipeline.pipeline_state import (
    PipelineState,
)
from src.pipeline.stage_result import (
    StageResult,
)
from src.services.pipeline_checkpoint_service import (
    PipelineCheckpointService,
)


def build_job() -> VideoJob:
    """Build a minimal checkpoint-history test job."""

    return VideoJob(
        project_name=(
            "Checkpoint History Test"
        ),
        channel_name="Mission Channel",
        niche="automation",
        topic=(
            "Checkpoint history preservation"
        ),
    )


def completed(
    stage: PipelineStageName,
) -> StageResult:
    return StageResult(
        stage=stage,
        status=(
            PipelineStageStatus.COMPLETED
        ),
    )


def skipped(
    stage: PipelineStageName,
) -> StageResult:
    return StageResult(
        stage=stage,
        status=(
            PipelineStageStatus.SKIPPED
        ),
        metadata={
            "resume_skip": True,
        },
    )


def failed(
    stage: PipelineStageName,
    message: str = (
        "Synthetic render failure."
    ),
) -> StageResult:
    return StageResult(
        stage=stage,
        status=(
            PipelineStageStatus.FAILED
        ),
        errors=[
            message,
        ],
    )


def waiting(
    stage: PipelineStageName,
) -> StageResult:
    return StageResult(
        stage=stage,
        status=(
            PipelineStageStatus
            .WAITING_FOR_USER
        ),
        warnings=[
            "Synthetic user input required.",
        ],
    )


def build_failed_checkpoint(
    job: VideoJob,
) -> PipelineCheckpoint:
    """Build the first failed checkpoint in a resume chain."""

    state = PipelineState(
        current_stage=(
            PipelineStageName.RENDER
        ),
        overall_progress=100,
        stages=[
            completed(
                PipelineStageName.VOICE
            ),
            failed(
                PipelineStageName.RENDER
            ),
        ],
        errors=[
            "Synthetic render failure.",
        ],
    )

    return (
        PipelineCheckpointService()
        .create(
            job=job,
            pipeline_state=state,
        )
    )


def test_resume_skip_preserves_historical_completion() -> None:
    job = build_job()

    previous = (
        build_failed_checkpoint(
            job
        )
    )

    resumed_state = PipelineState(
        current_stage=(
            PipelineStageName.RENDER
        ),
        overall_progress=100,
        stages=[
            skipped(
                PipelineStageName.VOICE
            ),
            failed(
                PipelineStageName.RENDER,
                "Second render failure.",
            ),
        ],
        errors=[
            "Second render failure.",
        ],
    )

    checkpoint = (
        PipelineCheckpointService()
        .create(
            job=job,
            pipeline_state=(
                resumed_state
            ),
            previous_checkpoint=(
                previous
            ),
        )
    )

    assert (
        PipelineStageName.VOICE
        in checkpoint.completed_stages
    )

    assert (
        PipelineStageName.VOICE
        not in checkpoint.skipped_stages
    )

    assert (
        checkpoint.failed_stage
        == PipelineStageName.RENDER
    )


def test_second_failure_remains_resumable() -> None:
    job = build_job()

    previous = (
        build_failed_checkpoint(
            job
        )
    )

    resumed_state = PipelineState(
        current_stage=(
            PipelineStageName.RENDER
        ),
        overall_progress=100,
        stages=[
            skipped(
                PipelineStageName.VOICE
            ),
            failed(
                PipelineStageName.RENDER,
                "Second render failure.",
            ),
        ],
    )

    checkpoint = (
        PipelineCheckpointService()
        .create(
            job=job,
            pipeline_state=(
                resumed_state
            ),
            previous_checkpoint=(
                previous
            ),
        )
    )

    assert (
        checkpoint.resumable
        is True
    )

    assert (
        checkpoint.completed_stages
        == [
            PipelineStageName.VOICE,
        ]
    )


def test_successful_resume_promotes_failed_stage() -> None:
    job = build_job()

    previous = (
        build_failed_checkpoint(
            job
        )
    )

    resumed_state = PipelineState(
        current_stage=(
            PipelineStageName.RENDER
        ),
        overall_progress=100,
        stages=[
            skipped(
                PipelineStageName.VOICE
            ),
            completed(
                PipelineStageName.RENDER
            ),
        ],
    )

    checkpoint = (
        PipelineCheckpointService()
        .create(
            job=job,
            pipeline_state=(
                resumed_state
            ),
            previous_checkpoint=(
                previous
            ),
        )
    )

    assert (
        checkpoint.completed_stages
        == [
            PipelineStageName.VOICE,
            PipelineStageName.RENDER,
        ]
    )

    assert (
        checkpoint.failed_stage
        is None
    )

    assert (
        checkpoint.resumable
        is False
    )


def test_history_results_are_preserved() -> None:
    job = build_job()

    previous = (
        build_failed_checkpoint(
            job
        )
    )

    historical_count = len(
        previous.stage_results
    )

    resumed_state = PipelineState(
        current_stage=(
            PipelineStageName.RENDER
        ),
        overall_progress=100,
        stages=[
            skipped(
                PipelineStageName.VOICE
            ),
            completed(
                PipelineStageName.RENDER
            ),
        ],
    )

    checkpoint = (
        PipelineCheckpointService()
        .create(
            job=job,
            pipeline_state=(
                resumed_state
            ),
            previous_checkpoint=(
                previous
            ),
        )
    )

    assert (
        len(
            checkpoint.stage_results
        )
        == historical_count + 2
    )

    render_results = [
        result
        for result
        in checkpoint.stage_results
        if (
            result.stage
            == PipelineStageName.RENDER
        )
    ]

    assert [
        result.status
        for result
        in render_results
    ] == [
        PipelineStageStatus.FAILED,
        PipelineStageStatus.COMPLETED,
    ]


def test_historical_diagnostics_are_preserved() -> None:
    job = build_job()

    previous = (
        build_failed_checkpoint(
            job
        )
    )

    resumed_state = PipelineState(
        current_stage=(
            PipelineStageName.RENDER
        ),
        stages=[
            skipped(
                PipelineStageName.VOICE
            ),
            completed(
                PipelineStageName.RENDER
            ),
        ],
        warnings=[
            "Resume warning.",
        ],
    )

    checkpoint = (
        PipelineCheckpointService()
        .create(
            job=job,
            pipeline_state=(
                resumed_state
            ),
            previous_checkpoint=(
                previous
            ),
        )
    )

    assert (
        "Synthetic render failure."
        in checkpoint.errors
    )

    assert (
        "Resume warning."
        in checkpoint.warnings
    )


def test_reexecuted_completed_stage_can_fail() -> None:
    job = build_job()

    previous = (
        PipelineCheckpointService()
        .create(
            job=job,
            pipeline_state=(
                PipelineState(
                    current_stage=(
                        PipelineStageName.VOICE
                    ),
                    stages=[
                        completed(
                            PipelineStageName.VOICE
                        ),
                    ],
                )
            ),
        )
    )

    resumed_state = PipelineState(
        current_stage=(
            PipelineStageName.VOICE
        ),
        stages=[
            failed(
                PipelineStageName.VOICE,
                "Voice rerun failed.",
            ),
        ],
    )

    checkpoint = (
        PipelineCheckpointService()
        .create(
            job=job,
            pipeline_state=(
                resumed_state
            ),
            previous_checkpoint=(
                previous
            ),
        )
    )

    assert (
        PipelineStageName.VOICE
        not in checkpoint.completed_stages
    )

    assert (
        checkpoint.failed_stage
        == PipelineStageName.VOICE
    )


def test_waiting_rerun_removes_old_completion() -> None:
    job = build_job()

    previous = (
        PipelineCheckpointService()
        .create(
            job=job,
            pipeline_state=(
                PipelineState(
                    current_stage=(
                        PipelineStageName
                        .ASSET_SELECTION
                    ),
                    stages=[
                        completed(
                            PipelineStageName
                            .ASSET_SELECTION
                        ),
                    ],
                )
            ),
        )
    )

    resumed_state = PipelineState(
        current_stage=(
            PipelineStageName
            .ASSET_SELECTION
        ),
        stages=[
            waiting(
                PipelineStageName
                .ASSET_SELECTION
            ),
        ],
    )

    checkpoint = (
        PipelineCheckpointService()
        .create(
            job=job,
            pipeline_state=(
                resumed_state
            ),
            previous_checkpoint=(
                previous
            ),
        )
    )

    assert (
        PipelineStageName.ASSET_SELECTION
        not in checkpoint.completed_stages
    )

    assert (
        checkpoint.waiting_stage
        == (
            PipelineStageName
            .ASSET_SELECTION
        )
    )


def test_wrong_job_history_is_rejected() -> None:
    first_job = build_job()
    second_job = build_job()

    previous = (
        build_failed_checkpoint(
            first_job
        )
    )

    state = PipelineState(
        current_stage=(
            PipelineStageName.RENDER
        ),
        stages=[
            completed(
                PipelineStageName.RENDER
            ),
        ],
    )

    try:
        (
            PipelineCheckpointService()
            .create(
                job=second_job,
                pipeline_state=state,
                previous_checkpoint=(
                    previous
                ),
            )
        )
    except ValueError as error:
        assert (
            "does not belong"
            in str(error)
        )
    else:
        raise AssertionError(
            "Cross-job checkpoint history "
            "must be rejected."
        )


def main() -> None:
    print()
    print(
        "Running Pipeline Checkpoint "
        "History tests..."
    )
    print()

    (
        test_resume_skip_preserves_historical_completion()
    )
    test_second_failure_remains_resumable()
    test_successful_resume_promotes_failed_stage()
    test_history_results_are_preserved()
    test_historical_diagnostics_are_preserved()
    test_reexecuted_completed_stage_can_fail()
    test_waiting_rerun_removes_old_completion()
    test_wrong_job_history_is_rejected()

    print()
    print(
        "Pipeline Checkpoint History tests "
        "completed successfully."
    )


if __name__ == "__main__":
    main()