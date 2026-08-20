from __future__ import annotations

from uuid import uuid4

from pydantic import ValidationError

from src.pipeline.pipeline_checkpoint import (
    PipelineCheckpoint,
)
from src.pipeline.pipeline_stage import (
    PipelineStageName,
    PipelineStageStatus,
)
from src.pipeline.stage_result import StageResult


def completed_result(
    stage: PipelineStageName,
) -> StageResult:
    return StageResult(
        stage=stage,
        status=(PipelineStageStatus.COMPLETED),
    )


def failed_result(
    stage: PipelineStageName,
) -> StageResult:
    return StageResult(
        stage=stage,
        status=(PipelineStageStatus.FAILED),
        errors=[
            "Synthetic checkpoint failure.",
        ],
    )


def waiting_result(
    stage: PipelineStageName,
) -> StageResult:
    return StageResult(
        stage=stage,
        status=(PipelineStageStatus.WAITING_FOR_USER),
    )


def test_completed_checkpoint() -> None:
    job_id = uuid4()

    checkpoint = PipelineCheckpoint(
        job_id=job_id,
        current_stage=(PipelineStageName.RENDER),
        overall_progress=100,
        completed_stages=[
            PipelineStageName.VOICE,
            PipelineStageName.RENDER,
        ],
        stage_results=[
            completed_result(PipelineStageName.VOICE),
            completed_result(PipelineStageName.RENDER),
        ],
    )

    assert checkpoint.job_id == job_id

    assert checkpoint.resumable is False

    assert checkpoint.terminally_failed is False

    assert checkpoint.waiting_for_user is False


def test_failed_checkpoint_is_resumable() -> None:
    checkpoint = PipelineCheckpoint(
        job_id=uuid4(),
        current_stage=(PipelineStageName.RENDER),
        overall_progress=75,
        completed_stages=[
            PipelineStageName.VOICE,
        ],
        failed_stage=(PipelineStageName.RENDER),
        stage_results=[
            completed_result(PipelineStageName.VOICE),
            failed_result(PipelineStageName.RENDER),
        ],
        total_retry_count=2,
    )

    assert checkpoint.resumable is True

    assert checkpoint.terminally_failed is True

    assert checkpoint.waiting_for_user is False

    assert checkpoint.total_retry_count == 2


def test_waiting_checkpoint_is_resumable() -> None:
    checkpoint = PipelineCheckpoint(
        job_id=uuid4(),
        current_stage=(PipelineStageName.ASSET_SELECTION),
        overall_progress=50,
        completed_stages=[
            PipelineStageName.VOICE,
        ],
        waiting_stage=(PipelineStageName.ASSET_SELECTION),
        stage_results=[
            completed_result(PipelineStageName.VOICE),
            waiting_result(PipelineStageName.ASSET_SELECTION),
        ],
    )

    assert checkpoint.resumable is True

    assert checkpoint.waiting_for_user is True

    assert checkpoint.terminally_failed is False


def test_failed_and_waiting_is_rejected() -> None:
    try:
        PipelineCheckpoint(
            job_id=uuid4(),
            current_stage=(PipelineStageName.RENDER),
            failed_stage=(PipelineStageName.RENDER),
            waiting_stage=(PipelineStageName.ASSET_SELECTION),
            stage_results=[
                failed_result(PipelineStageName.RENDER),
                waiting_result(PipelineStageName.ASSET_SELECTION),
            ],
        )
    except ValidationError as error:
        assert "cannot be failed and waiting" in str(error)
    else:
        raise AssertionError("Contradictory checkpoint " "must fail.")


def test_failed_stage_cannot_be_completed() -> None:
    try:
        PipelineCheckpoint(
            job_id=uuid4(),
            current_stage=(PipelineStageName.RENDER),
            completed_stages=[
                PipelineStageName.RENDER,
            ],
            failed_stage=(PipelineStageName.RENDER),
            stage_results=[
                failed_result(PipelineStageName.RENDER),
            ],
        )
    except ValidationError as error:
        assert "cannot also be completed" in str(error)
    else:
        raise AssertionError("Failed/completed checkpoint " "conflict must fail.")


def test_waiting_stage_cannot_be_completed() -> None:
    try:
        PipelineCheckpoint(
            job_id=uuid4(),
            current_stage=(PipelineStageName.ASSET_SELECTION),
            completed_stages=[
                (PipelineStageName.ASSET_SELECTION),
            ],
            waiting_stage=(PipelineStageName.ASSET_SELECTION),
            stage_results=[
                waiting_result(PipelineStageName.ASSET_SELECTION),
            ],
        )
    except ValidationError as error:
        assert "cannot also be completed" in str(error)
    else:
        raise AssertionError("Waiting/completed checkpoint " "conflict must fail.")


def test_completed_stage_requires_result() -> None:
    try:
        PipelineCheckpoint(
            job_id=uuid4(),
            current_stage=(PipelineStageName.VOICE),
            completed_stages=[
                PipelineStageName.VOICE,
            ],
            stage_results=[],
        )
    except ValidationError as error:
        assert "must have a StageResult" in str(error)
    else:
        raise AssertionError("Completed stage without result " "must fail.")


def test_failed_stage_requires_failed_result() -> None:
    try:
        PipelineCheckpoint(
            job_id=uuid4(),
            current_stage=(PipelineStageName.RENDER),
            failed_stage=(PipelineStageName.RENDER),
            stage_results=[
                completed_result(PipelineStageName.RENDER),
            ],
        )
    except ValidationError as error:
        assert "matching failed StageResult" in str(error)
    else:
        raise AssertionError("Failed stage without failed result " "must fail.")


def test_waiting_stage_requires_waiting_result() -> None:
    try:
        PipelineCheckpoint(
            job_id=uuid4(),
            current_stage=(PipelineStageName.ASSET_SELECTION),
            waiting_stage=(PipelineStageName.ASSET_SELECTION),
            stage_results=[
                completed_result(PipelineStageName.ASSET_SELECTION),
            ],
        )
    except ValidationError as error:
        assert "WAITING_FOR_USER" in str(error)
    else:
        raise AssertionError("Waiting stage without waiting " "result must fail.")


def test_stage_lists_are_deduplicated() -> None:
    checkpoint = PipelineCheckpoint(
        job_id=uuid4(),
        current_stage=(PipelineStageName.RENDER),
        completed_stages=[
            PipelineStageName.VOICE,
            PipelineStageName.VOICE,
        ],
        skipped_stages=[
            PipelineStageName.SCRIPT,
            PipelineStageName.SCRIPT,
        ],
        stage_results=[
            completed_result(PipelineStageName.VOICE),
        ],
    )

    assert checkpoint.completed_stages == [
        PipelineStageName.VOICE,
    ]

    assert checkpoint.skipped_stages == [
        PipelineStageName.SCRIPT,
    ]


def test_diagnostics_are_normalized() -> None:
    checkpoint = PipelineCheckpoint(
        job_id=uuid4(),
        current_stage=(PipelineStageName.VOICE),
        warnings=[
            " Warning. ",
            "Warning.",
        ],
        errors=[
            " Error. ",
            "Error.",
        ],
    )

    assert checkpoint.warnings == [
        "Warning.",
    ]

    assert checkpoint.errors == [
        "Error.",
    ]


def test_progress_bounds() -> None:
    for progress in (
        -1,
        101,
    ):
        try:
            PipelineCheckpoint(
                job_id=uuid4(),
                current_stage=(PipelineStageName.VOICE),
                overall_progress=progress,
            )
        except ValidationError:
            pass
        else:
            raise AssertionError("Invalid checkpoint progress " "must fail.")


def test_retry_count_cannot_be_negative() -> None:
    try:
        PipelineCheckpoint(
            job_id=uuid4(),
            current_stage=(PipelineStageName.VOICE),
            total_retry_count=-1,
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("Negative checkpoint retry count " "must fail.")


def main() -> None:
    print()
    print("Running Pipeline Checkpoint tests...")
    print()

    test_completed_checkpoint()
    test_failed_checkpoint_is_resumable()
    test_waiting_checkpoint_is_resumable()
    test_failed_and_waiting_is_rejected()
    test_failed_stage_cannot_be_completed()
    test_waiting_stage_cannot_be_completed()
    test_completed_stage_requires_result()
    test_failed_stage_requires_failed_result()
    test_waiting_stage_requires_waiting_result()
    test_stage_lists_are_deduplicated()
    test_diagnostics_are_normalized()
    test_progress_bounds()
    test_retry_count_cannot_be_negative()

    print()
    print("Pipeline Checkpoint tests " "completed successfully.")


if __name__ == "__main__":
    main()
