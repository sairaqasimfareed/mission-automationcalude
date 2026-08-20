from __future__ import annotations

from pydantic import ValidationError

from src.pipeline.pipeline_stage import (
    PipelineStageName,
    PipelineStageStatus,
)
from src.pipeline.stage_result import StageResult


def test_completed_result() -> None:
    result = StageResult(
        stage=PipelineStageName.VOICE,
        status=PipelineStageStatus.COMPLETED,
    )

    assert result.successful is True
    assert result.failed is False
    assert result.waiting_for_user is False

    assert result.retry_count == 0
    assert result.attempted_execution_count == 1


def test_failed_result() -> None:
    result = StageResult(
        stage=PipelineStageName.RENDER,
        status=PipelineStageStatus.FAILED,
        errors=[
            "Synthetic render failure.",
        ],
    )

    assert result.successful is False
    assert result.failed is True
    assert result.waiting_for_user is False


def test_waiting_result() -> None:
    result = StageResult(
        stage=(PipelineStageName.ASSET_SELECTION),
        status=(PipelineStageStatus.WAITING_FOR_USER),
    )

    assert result.successful is False
    assert result.failed is False
    assert result.waiting_for_user is True


def test_retry_count_tracks_retries() -> None:
    result = StageResult(
        stage=PipelineStageName.VOICE,
        status=PipelineStageStatus.COMPLETED,
        retry_count=2,
    )

    assert result.retry_count == 2

    assert result.attempted_execution_count == 3


def test_retry_count_cannot_be_negative() -> None:
    try:
        StageResult(
            stage=PipelineStageName.VOICE,
            status=PipelineStageStatus.COMPLETED,
            retry_count=-1,
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("Negative retry count must fail.")


def test_progress_bounds() -> None:
    for progress in (
        -1,
        101,
    ):
        try:
            StageResult(
                stage=PipelineStageName.VOICE,
                status=(PipelineStageStatus.COMPLETED),
                progress_percent=progress,
            )
        except ValidationError:
            pass
        else:
            raise AssertionError("Invalid progress percentage " "must fail.")


def test_failed_result_requires_error() -> None:
    try:
        StageResult(
            stage=PipelineStageName.RENDER,
            status=PipelineStageStatus.FAILED,
        )
    except ValidationError as error:
        assert "requires at least one error" in str(error)
    else:
        raise AssertionError("Failed result without an error " "must fail validation.")


def test_completed_result_rejects_errors() -> None:
    try:
        StageResult(
            stage=PipelineStageName.VOICE,
            status=(PipelineStageStatus.COMPLETED),
            errors=[
                "Contradictory error.",
            ],
        )
    except ValidationError as error:
        assert "cannot contain errors" in str(error)
    else:
        raise AssertionError(
            "Completed result containing errors " "must fail validation."
        )


def test_diagnostics_are_normalized() -> None:
    result = StageResult(
        stage=PipelineStageName.VOICE,
        status=PipelineStageStatus.FAILED,
        warnings=[
            " First warning. ",
            "",
            "First warning.",
            "Second warning.",
        ],
        errors=[
            " Failure. ",
            "Failure.",
        ],
    )

    assert result.warnings == [
        "First warning.",
        "Second warning.",
    ]

    assert result.errors == [
        "Failure.",
    ]


def test_metadata_is_typed_mapping() -> None:
    result = StageResult(
        stage=PipelineStageName.VOICE,
        status=PipelineStageStatus.COMPLETED,
        metadata={
            "provider": "synthetic",
            "attempts": 1,
        },
    )

    assert result.metadata["provider"] == "synthetic"

    assert result.metadata["attempts"] == 1


def test_with_retry_count_returns_copy() -> None:
    original = StageResult(
        stage=PipelineStageName.VOICE,
        status=PipelineStageStatus.COMPLETED,
    )

    retried = original.with_retry_count(2)

    assert original.retry_count == 0

    assert retried.retry_count == 2

    assert retried.attempted_execution_count == 3

    assert retried is not original


def test_with_retry_count_rejects_negative_value() -> None:
    result = StageResult(
        stage=PipelineStageName.VOICE,
        status=PipelineStageStatus.COMPLETED,
    )

    try:
        result.with_retry_count(-1)
    except ValueError as error:
        assert "cannot be negative" in str(error)
    else:
        raise AssertionError("Negative retry count must fail.")


def main() -> None:
    print()
    print("Running Stage Result tests...")
    print()

    test_completed_result()
    test_failed_result()
    test_waiting_result()
    test_retry_count_tracks_retries()
    test_retry_count_cannot_be_negative()
    test_progress_bounds()
    test_failed_result_requires_error()
    test_completed_result_rejects_errors()
    test_diagnostics_are_normalized()
    test_metadata_is_typed_mapping()
    test_with_retry_count_returns_copy()
    (test_with_retry_count_rejects_negative_value())

    print()
    print("Stage Result tests " "completed successfully.")


if __name__ == "__main__":
    main()
