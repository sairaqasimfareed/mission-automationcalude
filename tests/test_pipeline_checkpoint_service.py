from __future__ import annotations

from src.models.video_job import VideoJob
from src.pipeline.pipeline_stage import (
    PipelineStageName,
    PipelineStageStatus,
)
from src.pipeline.pipeline_state import PipelineState
from src.pipeline.stage_result import StageResult
from src.services.pipeline_checkpoint_service import (
    PipelineCheckpointService,
)


def build_job() -> VideoJob:
    """Build a minimal valid checkpoint test job."""

    return VideoJob(
        project_name="Checkpoint Service Test",
        channel_name="Mission Channel",
        niche="automation",
        topic="Checkpoint snapshot creation",
    )


def completed_result(
    stage: PipelineStageName,
    *,
    retry_count: int = 0,
) -> StageResult:
    return StageResult(
        stage=stage,
        status=(
            PipelineStageStatus.COMPLETED
        ),
        retry_count=retry_count,
    )


def failed_result(
    stage: PipelineStageName,
    *,
    retry_count: int = 0,
) -> StageResult:
    return StageResult(
        stage=stage,
        status=(
            PipelineStageStatus.FAILED
        ),
        retry_count=retry_count,
        errors=[
            "Synthetic checkpoint failure.",
        ],
    )


def waiting_result(
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


def skipped_result(
    stage: PipelineStageName,
) -> StageResult:
    return StageResult(
        stage=stage,
        status=(
            PipelineStageStatus.SKIPPED
        ),
    )


def test_completed_checkpoint_snapshot() -> None:
    job = build_job()

    state = PipelineState(
        current_stage=(
            PipelineStageName.RENDER
        ),
        overall_progress=100,
        stages=[
            completed_result(
                PipelineStageName.VOICE
            ),
            completed_result(
                PipelineStageName.RENDER
            ),
        ],
    )

    checkpoint = (
        PipelineCheckpointService()
        .create(
            job=job,
            pipeline_state=state,
        )
    )

    assert (
        checkpoint.job_id
        == job.id
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
        checkpoint.waiting_stage
        is None
    )

    assert (
        checkpoint.resumable
        is False
    )


def test_failed_checkpoint_snapshot() -> None:
    job = build_job()

    job.retry_count = 2

    state = PipelineState(
        current_stage=(
            PipelineStageName.RENDER
        ),
        overall_progress=75,
        stages=[
            completed_result(
                PipelineStageName.VOICE
            ),
            failed_result(
                PipelineStageName.RENDER,
                retry_count=2,
            ),
        ],
        errors=[
            "Synthetic checkpoint failure.",
        ],
    )

    checkpoint = (
        PipelineCheckpointService()
        .create(
            job=job,
            pipeline_state=state,
        )
    )

    assert (
        checkpoint.failed_stage
        == PipelineStageName.RENDER
    )

    assert (
        checkpoint.completed_stages
        == [
            PipelineStageName.VOICE,
        ]
    )

    assert (
        checkpoint.total_retry_count
        == 2
    )

    assert (
        checkpoint.resumable
        is True
    )

    assert (
        checkpoint.errors
        == [
            "Synthetic checkpoint failure.",
        ]
    )


def test_waiting_checkpoint_snapshot() -> None:
    job = build_job()

    state = PipelineState(
        current_stage=(
            PipelineStageName
            .ASSET_SELECTION
        ),
        overall_progress=50,
        stages=[
            completed_result(
                PipelineStageName.VOICE
            ),
            waiting_result(
                PipelineStageName
                .ASSET_SELECTION
            ),
        ],
        warnings=[
            "Synthetic user input required.",
        ],
    )

    checkpoint = (
        PipelineCheckpointService()
        .create(
            job=job,
            pipeline_state=state,
        )
    )

    assert (
        checkpoint.waiting_stage
        == (
            PipelineStageName
            .ASSET_SELECTION
        )
    )

    assert (
        checkpoint.failed_stage
        is None
    )

    assert (
        checkpoint.waiting_for_user
        is True
    )

    assert (
        checkpoint.resumable
        is True
    )


def test_skipped_stages_are_captured() -> None:
    job = build_job()

    state = PipelineState(
        current_stage=(
            PipelineStageName.RENDER
        ),
        overall_progress=100,
        stages=[
            skipped_result(
                PipelineStageName
                .BACKGROUND_MUSIC
            ),
            completed_result(
                PipelineStageName.RENDER
            ),
        ],
    )

    checkpoint = (
        PipelineCheckpointService()
        .create(
            job=job,
            pipeline_state=state,
        )
    )

    assert (
        checkpoint.skipped_stages
        == [
            (
                PipelineStageName
                .BACKGROUND_MUSIC
            ),
        ]
    )


def test_metadata_is_copied() -> None:
    job = build_job()

    state = PipelineState(
        current_stage=(
            PipelineStageName.VOICE
        ),
    )

    metadata = {
        "source": "synthetic",
        "resume_allowed": True,
    }

    checkpoint = (
        PipelineCheckpointService()
        .create(
            job=job,
            pipeline_state=state,
            metadata=metadata,
        )
    )

    assert (
        checkpoint.metadata
        == metadata
    )

    assert (
        checkpoint.metadata
        is not metadata
    )


def test_stage_results_are_snapshotted() -> None:
    job = build_job()

    result = completed_result(
        PipelineStageName.VOICE
    )

    state = PipelineState(
        current_stage=(
            PipelineStageName.VOICE
        ),
        stages=[
            result,
        ],
    )

    checkpoint = (
        PipelineCheckpointService()
        .create(
            job=job,
            pipeline_state=state,
        )
    )

    assert (
        checkpoint.stage_results
        == [
            result,
        ]
    )

    assert (
        checkpoint.stage_results
        is not state.stages
    )


def test_latest_failed_stage_is_authoritative() -> None:
    job = build_job()

    state = PipelineState(
        current_stage=(
            PipelineStageName.RENDER
        ),
        stages=[
            failed_result(
                PipelineStageName.VOICE
            ),
            failed_result(
                PipelineStageName.RENDER
            ),
        ],
        errors=[
            "Synthetic checkpoint failure.",
        ],
    )

    checkpoint = (
        PipelineCheckpointService()
        .create(
            job=job,
            pipeline_state=state,
        )
    )

    assert (
        checkpoint.failed_stage
        == PipelineStageName.RENDER
    )


def test_diagnostics_are_preserved() -> None:
    job = build_job()

    state = PipelineState(
        current_stage=(
            PipelineStageName.RENDER
        ),
        warnings=[
            "Warning A.",
            "Warning B.",
        ],
        errors=[
            "Error A.",
        ],
    )

    checkpoint = (
        PipelineCheckpointService()
        .create(
            job=job,
            pipeline_state=state,
        )
    )

    assert (
        checkpoint.warnings
        == [
            "Warning A.",
            "Warning B.",
        ]
    )

    assert (
        checkpoint.errors
        == [
            "Error A.",
        ]
    )


def main() -> None:
    print()
    print(
        "Running Pipeline Checkpoint "
        "Service tests..."
    )
    print()

    test_completed_checkpoint_snapshot()
    test_failed_checkpoint_snapshot()
    test_waiting_checkpoint_snapshot()
    test_skipped_stages_are_captured()
    test_metadata_is_copied()
    test_stage_results_are_snapshotted()
    test_latest_failed_stage_is_authoritative()
    test_diagnostics_are_preserved()

    print()
    print(
        "Pipeline Checkpoint Service tests "
        "completed successfully."
    )


if __name__ == "__main__":
    main()