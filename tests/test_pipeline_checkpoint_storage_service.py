from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from src.pipeline.pipeline_checkpoint import (
    PipelineCheckpoint,
)
from src.pipeline.pipeline_stage import (
    PipelineStageName,
    PipelineStageStatus,
)
from src.pipeline.stage_result import StageResult
from src.services.pipeline_checkpoint_storage_service import (
    PipelineCheckpointCorruptError,
    PipelineCheckpointStorageService,
)


def build_completed_result(
    stage: PipelineStageName,
) -> StageResult:
    """Build one completed stage result."""

    return StageResult(
        stage=stage,
        status=(
            PipelineStageStatus.COMPLETED
        ),
    )


def build_failed_result(
    stage: PipelineStageName,
) -> StageResult:
    """Build one failed stage result."""

    return StageResult(
        stage=stage,
        status=(
            PipelineStageStatus.FAILED
        ),
        errors=[
            "Synthetic checkpoint failure.",
        ],
    )


def build_checkpoint(
    *,
    job_id: UUID | None = None,
    checkpoint_id: UUID | None = None,
    created_at: datetime | None = None,
    failed: bool = False,
) -> PipelineCheckpoint:
    """Build a valid checkpoint for persistence tests."""

    resolved_job_id = (
        job_id
        or uuid4()
    )

    resolved_checkpoint_id = (
        checkpoint_id
        or uuid4()
    )

    if failed:
        return PipelineCheckpoint(
            checkpoint_id=(
                resolved_checkpoint_id
            ),
            job_id=resolved_job_id,
            current_stage=(
                PipelineStageName.RENDER
            ),
            overall_progress=75,
            completed_stages=[
                PipelineStageName.VOICE,
            ],
            failed_stage=(
                PipelineStageName.RENDER
            ),
            stage_results=[
                build_completed_result(
                    PipelineStageName.VOICE
                ),
                build_failed_result(
                    PipelineStageName.RENDER
                ),
            ],
            total_retry_count=2,
            warnings=[
                "Synthetic checkpoint warning.",
            ],
            errors=[
                "Synthetic checkpoint failure.",
            ],
            created_at=(
                created_at
                or datetime.now(
                    UTC
                )
            ),
            metadata={
                "source": "storage-test",
            },
        )

    return PipelineCheckpoint(
        checkpoint_id=(
            resolved_checkpoint_id
        ),
        job_id=resolved_job_id,
        current_stage=(
            PipelineStageName.RENDER
        ),
        overall_progress=100,
        completed_stages=[
            PipelineStageName.VOICE,
            PipelineStageName.RENDER,
        ],
        stage_results=[
            build_completed_result(
                PipelineStageName.VOICE
            ),
            build_completed_result(
                PipelineStageName.RENDER
            ),
        ],
        created_at=(
            created_at
            or datetime.now(
                UTC
            )
        ),
        metadata={
            "source": "storage-test",
        },
    )


def build_service(
    root: Path,
) -> PipelineCheckpointStorageService:
    """Build checkpoint storage rooted in a temporary directory."""

    return PipelineCheckpointStorageService(
        storage_root=root,
    )


def test_storage_root_is_created(
    tmp_path: Path,
) -> None:
    storage_root = (
        tmp_path
        / "nested"
        / "checkpoints"
    )

    assert (
        storage_root.exists()
        is False
    )

    service = build_service(
        storage_root
    )

    assert (
        service.storage_root.exists()
        is True
    )

    assert (
        service.storage_root.is_dir()
        is True
    )


def test_save_creates_checkpoint_file(
    tmp_path: Path,
) -> None:
    service = build_service(
        tmp_path
        / "checkpoints"
    )

    checkpoint = build_checkpoint()

    path = service.save(
        checkpoint
    )

    assert path.exists()

    assert path.is_file()

    assert (
        path.name
        == (
            f"{checkpoint.checkpoint_id}.json"
        )
    )

    assert (
        path.parent.name
        == str(
            checkpoint.job_id
        )
    )


def test_save_and_load_round_trip(
    tmp_path: Path,
) -> None:
    service = build_service(
        tmp_path
        / "checkpoints"
    )

    checkpoint = build_checkpoint(
        failed=True
    )

    service.save(
        checkpoint
    )

    loaded = service.load(
        job_id=(
            checkpoint.job_id
        ),
        checkpoint_id=(
            checkpoint.checkpoint_id
        ),
    )

    assert loaded is not None

    assert (
        loaded
        == checkpoint
    )

    assert (
        loaded.checkpoint_id
        == checkpoint.checkpoint_id
    )

    assert (
        loaded.job_id
        == checkpoint.job_id
    )

    assert (
        loaded.total_retry_count
        == 2
    )

    assert (
        loaded.failed_stage
        == PipelineStageName.RENDER
    )


def test_saved_json_is_valid_and_readable(
    tmp_path: Path,
) -> None:
    service = build_service(
        tmp_path
        / "checkpoints"
    )

    checkpoint = build_checkpoint()

    path = service.save(
        checkpoint
    )

    raw = path.read_text(
        encoding="utf-8"
    )

    payload = json.loads(
        raw
    )

    assert isinstance(
        payload,
        dict,
    )

    assert (
        payload[
            "checkpoint_id"
        ]
        == str(
            checkpoint.checkpoint_id
        )
    )

    assert (
        payload[
            "job_id"
        ]
        == str(
            checkpoint.job_id
        )
    )

    assert (
        payload[
            "current_stage"
        ]
        == (
            PipelineStageName.RENDER.value
        )
    )


def test_save_overwrites_same_checkpoint_atomically(
    tmp_path: Path,
) -> None:
    service = build_service(
        tmp_path
        / "checkpoints"
    )

    job_id = uuid4()

    checkpoint_id = uuid4()

    first = build_checkpoint(
        job_id=job_id,
        checkpoint_id=checkpoint_id,
    )

    path = service.save(
        first
    )

    second = build_checkpoint(
        job_id=job_id,
        checkpoint_id=checkpoint_id,
        failed=True,
    )

    second_path = service.save(
        second
    )

    assert (
        second_path
        == path
    )

    loaded = service.load(
        job_id=job_id,
        checkpoint_id=checkpoint_id,
    )

    assert loaded is not None

    assert (
        loaded.failed_stage
        == PipelineStageName.RENDER
    )

    assert (
        loaded.total_retry_count
        == 2
    )


def test_atomic_save_leaves_no_temp_files(
    tmp_path: Path,
) -> None:
    service = build_service(
        tmp_path
        / "checkpoints"
    )

    checkpoint = build_checkpoint()

    path = service.save(
        checkpoint
    )

    temporary_files = [
        candidate
        for candidate
        in path.parent.iterdir()
        if candidate.suffix
        == ".tmp"
    ]

    assert (
        temporary_files
        == []
    )


def test_missing_checkpoint_returns_none(
    tmp_path: Path,
) -> None:
    service = build_service(
        tmp_path
        / "checkpoints"
    )

    result = service.load(
        job_id=uuid4(),
        checkpoint_id=uuid4(),
    )

    assert result is None


def test_exists_reports_checkpoint_presence(
    tmp_path: Path,
) -> None:
    service = build_service(
        tmp_path
        / "checkpoints"
    )

    checkpoint = build_checkpoint()

    assert (
        service.exists(
            job_id=(
                checkpoint.job_id
            ),
            checkpoint_id=(
                checkpoint.checkpoint_id
            ),
        )
        is False
    )

    service.save(
        checkpoint
    )

    assert (
        service.exists(
            job_id=(
                checkpoint.job_id
            ),
            checkpoint_id=(
                checkpoint.checkpoint_id
            ),
        )
        is True
    )


def test_load_latest_returns_none_for_missing_job(
    tmp_path: Path,
) -> None:
    service = build_service(
        tmp_path
        / "checkpoints"
    )

    latest = service.load_latest(
        job_id=uuid4(),
    )

    assert latest is None


def test_load_latest_returns_newest_created_checkpoint(
    tmp_path: Path,
) -> None:
    service = build_service(
        tmp_path
        / "checkpoints"
    )

    job_id = uuid4()

    base_time = datetime.now(
        UTC
    )

    oldest = build_checkpoint(
        job_id=job_id,
        created_at=(
            base_time
            - timedelta(
                minutes=10
            )
        ),
    )

    newest = build_checkpoint(
        job_id=job_id,
        created_at=(
            base_time
            + timedelta(
                minutes=10
            )
        ),
        failed=True,
    )

    middle = build_checkpoint(
        job_id=job_id,
        created_at=base_time,
    )

    service.save(
        newest
    )

    service.save(
        oldest
    )

    service.save(
        middle
    )

    latest = service.load_latest(
        job_id=job_id,
    )

    assert latest is not None

    assert (
        latest.checkpoint_id
        == newest.checkpoint_id
    )


def test_latest_uses_checkpoint_time_not_file_mtime(
    tmp_path: Path,
) -> None:
    service = build_service(
        tmp_path
        / "checkpoints"
    )

    job_id = uuid4()

    now = datetime.now(
        UTC
    )

    older_checkpoint = (
        build_checkpoint(
            job_id=job_id,
            created_at=(
                now
                - timedelta(
                    hours=1
                )
            ),
        )
    )

    newer_checkpoint = (
        build_checkpoint(
            job_id=job_id,
            created_at=(
                now
                + timedelta(
                    hours=1
                )
            ),
        )
    )

    service.save(
        newer_checkpoint
    )

    older_path = service.save(
        older_checkpoint
    )

    # The older checkpoint is written last, so filesystem mtime may be
    # newer. The model's created_at must still remain authoritative.
    assert older_path.exists()

    latest = service.load_latest(
        job_id=job_id,
    )

    assert latest is not None

    assert (
        latest.checkpoint_id
        == newer_checkpoint.checkpoint_id
    )


def test_list_for_job_returns_oldest_first(
    tmp_path: Path,
) -> None:
    service = build_service(
        tmp_path
        / "checkpoints"
    )

    job_id = uuid4()

    now = datetime.now(
        UTC
    )

    first = build_checkpoint(
        job_id=job_id,
        created_at=(
            now
            - timedelta(
                minutes=2
            )
        ),
    )

    second = build_checkpoint(
        job_id=job_id,
        created_at=(
            now
            - timedelta(
                minutes=1
            )
        ),
    )

    third = build_checkpoint(
        job_id=job_id,
        created_at=now,
    )

    service.save(
        third
    )

    service.save(
        first
    )

    service.save(
        second
    )

    checkpoints = (
        service.list_for_job(
            job_id=job_id,
        )
    )

    assert [
        checkpoint.checkpoint_id
        for checkpoint
        in checkpoints
    ] == [
        first.checkpoint_id,
        second.checkpoint_id,
        third.checkpoint_id,
    ]


def test_list_for_job_returns_empty_for_missing_job(
    tmp_path: Path,
) -> None:
    service = build_service(
        tmp_path
        / "checkpoints"
    )

    checkpoints = (
        service.list_for_job(
            job_id=uuid4(),
        )
    )

    assert checkpoints == []


def test_jobs_are_isolated(
    tmp_path: Path,
) -> None:
    service = build_service(
        tmp_path
        / "checkpoints"
    )

    first = build_checkpoint()

    second = build_checkpoint()

    service.save(
        first
    )

    service.save(
        second
    )

    first_list = service.list_for_job(
        job_id=first.job_id,
    )

    second_list = service.list_for_job(
        job_id=second.job_id,
    )

    assert [
        checkpoint.checkpoint_id
        for checkpoint
        in first_list
    ] == [
        first.checkpoint_id,
    ]

    assert [
        checkpoint.checkpoint_id
        for checkpoint
        in second_list
    ] == [
        second.checkpoint_id,
    ]


def test_delete_existing_checkpoint(
    tmp_path: Path,
) -> None:
    service = build_service(
        tmp_path
        / "checkpoints"
    )

    checkpoint = build_checkpoint()

    service.save(
        checkpoint
    )

    deleted = service.delete(
        job_id=(
            checkpoint.job_id
        ),
        checkpoint_id=(
            checkpoint.checkpoint_id
        ),
    )

    assert deleted is True

    assert (
        service.exists(
            job_id=(
                checkpoint.job_id
            ),
            checkpoint_id=(
                checkpoint.checkpoint_id
            ),
        )
        is False
    )


def test_delete_missing_checkpoint_returns_false(
    tmp_path: Path,
) -> None:
    service = build_service(
        tmp_path
        / "checkpoints"
    )

    deleted = service.delete(
        job_id=uuid4(),
        checkpoint_id=uuid4(),
    )

    assert deleted is False


def test_corrupt_json_is_rejected(
    tmp_path: Path,
) -> None:
    service = build_service(
        tmp_path
        / "checkpoints"
    )

    job_id = uuid4()

    checkpoint_id = uuid4()

    job_directory = (
        service.storage_root
        / str(job_id)
    )

    job_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    path = (
        job_directory
        / f"{checkpoint_id}.json"
    )

    path.write_text(
        "{ this is not valid json",
        encoding="utf-8",
    )

    try:
        service.load(
            job_id=job_id,
            checkpoint_id=checkpoint_id,
        )
    except PipelineCheckpointCorruptError as error:
        assert (
            "invalid JSON"
            in str(error)
        )
    else:
        raise AssertionError(
            "Corrupt checkpoint JSON "
            "must fail."
        )


def test_non_object_json_is_rejected(
    tmp_path: Path,
) -> None:
    service = build_service(
        tmp_path
        / "checkpoints"
    )

    job_id = uuid4()

    checkpoint_id = uuid4()

    job_directory = (
        service.storage_root
        / str(job_id)
    )

    job_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    path = (
        job_directory
        / f"{checkpoint_id}.json"
    )

    path.write_text(
        json.dumps(
            [
                "not",
                "an",
                "object",
            ]
        ),
        encoding="utf-8",
    )

    try:
        service.load(
            job_id=job_id,
            checkpoint_id=checkpoint_id,
        )
    except PipelineCheckpointCorruptError as error:
        assert (
            "root must be an object"
            in str(error)
        )
    else:
        raise AssertionError(
            "Non-object checkpoint JSON "
            "must fail."
        )


def test_schema_invalid_json_is_rejected(
    tmp_path: Path,
) -> None:
    service = build_service(
        tmp_path
        / "checkpoints"
    )

    job_id = uuid4()

    checkpoint_id = uuid4()

    job_directory = (
        service.storage_root
        / str(job_id)
    )

    job_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    path = (
        job_directory
        / f"{checkpoint_id}.json"
    )

    payload = {
        "checkpoint_id": str(
            checkpoint_id
        ),
        "job_id": str(
            job_id
        ),
        "current_stage": "not-a-stage",
    }

    path.write_text(
        json.dumps(
            payload
        ),
        encoding="utf-8",
    )

    try:
        service.load(
            job_id=job_id,
            checkpoint_id=checkpoint_id,
        )
    except PipelineCheckpointCorruptError as error:
        assert (
            "does not satisfy"
            in str(error)
        )
    else:
        raise AssertionError(
            "Schema-invalid checkpoint "
            "must fail."
        )


def test_filename_checkpoint_id_mismatch_is_rejected(
    tmp_path: Path,
) -> None:
    service = build_service(
        tmp_path
        / "checkpoints"
    )

    checkpoint = build_checkpoint()

    path = service.save(
        checkpoint
    )

    wrong_id = uuid4()

    wrong_path = (
        path.parent
        / f"{wrong_id}.json"
    )

    path.rename(
        wrong_path
    )

    try:
        service.load(
            job_id=(
                checkpoint.job_id
            ),
            checkpoint_id=wrong_id,
        )
    except PipelineCheckpointCorruptError as error:
        assert (
            "does not match its filename"
            in str(error)
        )
    else:
        raise AssertionError(
            "Checkpoint filename/ID mismatch "
            "must fail."
        )


def test_job_directory_mismatch_is_rejected(
    tmp_path: Path,
) -> None:
    service = build_service(
        tmp_path
        / "checkpoints"
    )

    checkpoint = build_checkpoint()

    original_path = service.save(
        checkpoint
    )

    wrong_job_id = uuid4()

    wrong_directory = (
        service.storage_root
        / str(wrong_job_id)
    )

    wrong_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    wrong_path = (
        wrong_directory
        / original_path.name
    )

    original_path.rename(
        wrong_path
    )

    try:
        service.load(
            job_id=wrong_job_id,
            checkpoint_id=(
                checkpoint.checkpoint_id
            ),
        )
    except PipelineCheckpointCorruptError as error:
        assert (
            "job ID does not match"
            in str(error)
        )
    else:
        raise AssertionError(
            "Checkpoint stored under the "
            "wrong job must fail."
        )


def test_load_latest_rejects_corrupt_checkpoint(
    tmp_path: Path,
) -> None:
    service = build_service(
        tmp_path
        / "checkpoints"
    )

    job_id = uuid4()

    valid = build_checkpoint(
        job_id=job_id,
    )

    service.save(
        valid
    )

    job_directory = (
        service.storage_root
        / str(job_id)
    )

    corrupt_path = (
        job_directory
        / f"{uuid4()}.json"
    )

    corrupt_path.write_text(
        "invalid-json",
        encoding="utf-8",
    )

    try:
        service.load_latest(
            job_id=job_id,
        )
    except PipelineCheckpointCorruptError:
        pass
    else:
        raise AssertionError(
            "Latest checkpoint lookup must "
            "not silently ignore corruption."
        )


def test_list_rejects_corrupt_checkpoint(
    tmp_path: Path,
) -> None:
    service = build_service(
        tmp_path
        / "checkpoints"
    )

    job_id = uuid4()

    checkpoint = build_checkpoint(
        job_id=job_id,
    )

    service.save(
        checkpoint
    )

    job_directory = (
        service.storage_root
        / str(job_id)
    )

    corrupt_path = (
        job_directory
        / f"{uuid4()}.json"
    )

    corrupt_path.write_text(
        "{}",
        encoding="utf-8",
    )

    try:
        service.list_for_job(
            job_id=job_id,
        )
    except PipelineCheckpointCorruptError:
        pass
    else:
        raise AssertionError(
            "Checkpoint listing must not "
            "silently ignore corruption."
        )


def test_unrelated_files_are_ignored(
    tmp_path: Path,
) -> None:
    service = build_service(
        tmp_path
        / "checkpoints"
    )

    checkpoint = build_checkpoint()

    path = service.save(
        checkpoint
    )

    unrelated_file = (
        path.parent
        / "notes.txt"
    )

    unrelated_file.write_text(
        "not a checkpoint",
        encoding="utf-8",
    )

    checkpoints = (
        service.list_for_job(
            job_id=(
                checkpoint.job_id
            ),
        )
    )

    assert len(
        checkpoints
    ) == 1

    latest = service.load_latest(
        job_id=(
            checkpoint.job_id
        ),
    )

    assert latest is not None

    assert (
        latest.checkpoint_id
        == checkpoint.checkpoint_id
    )


def main() -> None:
    print()
    print(
        "Running Pipeline Checkpoint "
        "Storage Service tests..."
    )
    print()

    # Tests requiring pytest's tmp_path fixture are intentionally
    # executed through pytest rather than this manual entry point.
    print(
        "Run this suite with pytest because "
        "it uses the tmp_path fixture."
    )


if __name__ == "__main__":
    main()