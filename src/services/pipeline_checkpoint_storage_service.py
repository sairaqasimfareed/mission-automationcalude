from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from src.pipeline.pipeline_checkpoint import (
    PipelineCheckpoint,
)


class PipelineCheckpointStorageError(RuntimeError):
    """Base error raised by checkpoint persistence."""


class PipelineCheckpointCorruptError(PipelineCheckpointStorageError):
    """Raised when a persisted checkpoint cannot be validated."""


class PipelineCheckpointStorageService:
    """
    Persist pipeline checkpoints in local project storage.

    Responsibilities:
    - serialize validated PipelineCheckpoint models;
    - write checkpoints atomically;
    - load and validate persisted checkpoints;
    - resolve the latest checkpoint for a job;
    - isolate filesystem persistence from orchestration logic.

    The directory layout is:

        <storage_root>/
            <job_id>/
                <checkpoint_id>.json

    This service intentionally owns persistence only. Creating
    checkpoints remains the responsibility of
    PipelineCheckpointService.
    """

    FILE_SUFFIX = ".json"

    def __init__(
        self,
        *,
        storage_root: str | Path,
    ) -> None:
        self.storage_root = Path(storage_root).expanduser().resolve()

        self.storage_root.mkdir(
            parents=True,
            exist_ok=True,
        )

    def save(
        self,
        checkpoint: PipelineCheckpoint,
    ) -> Path:
        """
        Persist one checkpoint atomically.

        A temporary file is written in the destination directory and
        then replaced atomically. This prevents a partially written
        checkpoint from becoming authoritative.
        """

        job_directory = self._job_directory(checkpoint.job_id)

        job_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        destination = self._checkpoint_path(checkpoint)

        payload = checkpoint.model_dump(
            mode="json",
        )

        self._atomic_write_json(
            destination=destination,
            payload=payload,
        )

        return destination

    def load(
        self,
        *,
        job_id: UUID,
        checkpoint_id: UUID,
    ) -> PipelineCheckpoint | None:
        """
        Load one checkpoint.

        Returns None when the requested checkpoint does not exist.
        Corrupt or schema-invalid checkpoint files raise a dedicated
        persistence error instead of being treated as missing.
        """

        path = self._job_directory(job_id) / f"{checkpoint_id}{self.FILE_SUFFIX}"

        if not path.exists():
            return None

        checkpoint = self._load_path(path)

        if checkpoint.job_id != job_id:
            raise PipelineCheckpointCorruptError(
                "Persisted checkpoint job ID does not " "match its storage location."
            )

        if checkpoint.checkpoint_id != checkpoint_id:
            raise PipelineCheckpointCorruptError(
                "Persisted checkpoint ID does not " "match its filename."
            )

        return checkpoint

    def load_latest(
        self,
        *,
        job_id: UUID,
    ) -> PipelineCheckpoint | None:
        """
        Return the newest valid persisted checkpoint for one job.

        The checkpoint creation timestamp is authoritative rather than
        filesystem modification time.
        """

        job_directory = self._job_directory(job_id)

        if not job_directory.exists():
            return None

        if not job_directory.is_dir():
            raise PipelineCheckpointStorageError(
                "Checkpoint job storage path is not " "a directory."
            )

        checkpoint_paths = sorted(
            path
            for path in job_directory.iterdir()
            if (path.is_file() and path.suffix == self.FILE_SUFFIX)
        )

        if not checkpoint_paths:
            return None

        checkpoints: list[PipelineCheckpoint] = []

        for path in checkpoint_paths:
            checkpoint = self._load_path(path)

            if checkpoint.job_id != job_id:
                raise PipelineCheckpointCorruptError(
                    "Persisted checkpoint job ID does "
                    "not match its storage location."
                )

            expected_name = f"{checkpoint.checkpoint_id}" f"{self.FILE_SUFFIX}"

            if path.name != expected_name:
                raise PipelineCheckpointCorruptError(
                    "Persisted checkpoint ID does not " "match its filename."
                )

            checkpoints.append(checkpoint)

        return max(
            checkpoints,
            key=lambda checkpoint: (
                checkpoint.created_at,
                str(checkpoint.checkpoint_id),
            ),
        )

    def list_job_ids(self) -> list[UUID]:
        """
        Return every job ID with at least one persisted checkpoint.

        This scans storage_root's immediate subdirectories, each of
        which is named after a job ID by construction (see
        _job_directory). Only directories that parse as a valid UUID
        and contain at least one checkpoint file are included, so
        stray non-job directories or an emptied job directory are
        silently skipped rather than raising.
        """

        if not self.storage_root.exists():
            return []

        job_ids: list[UUID] = []

        for entry in sorted(self.storage_root.iterdir()):
            if not entry.is_dir():
                continue

            try:
                job_id = UUID(entry.name)
            except ValueError:
                continue

            has_checkpoint = any(
                path.is_file() and path.suffix == self.FILE_SUFFIX
                for path in entry.iterdir()
            )

            if has_checkpoint:
                job_ids.append(job_id)

        return job_ids

    def exists(
        self,
        *,
        job_id: UUID,
        checkpoint_id: UUID,
    ) -> bool:
        """Return whether one checkpoint file exists."""

        path = self._job_directory(job_id) / f"{checkpoint_id}{self.FILE_SUFFIX}"

        return path.exists() and path.is_file()

    def list_for_job(
        self,
        *,
        job_id: UUID,
    ) -> list[PipelineCheckpoint]:
        """
        Load all persisted checkpoints for one job.

        Results are returned oldest-first using checkpoint creation
        time, with checkpoint ID as a deterministic tie breaker.
        """

        job_directory = self._job_directory(job_id)

        if not job_directory.exists():
            return []

        if not job_directory.is_dir():
            raise PipelineCheckpointStorageError(
                "Checkpoint job storage path is not " "a directory."
            )

        checkpoints: list[PipelineCheckpoint] = []

        for path in sorted(job_directory.iterdir()):
            if not path.is_file() or path.suffix != self.FILE_SUFFIX:
                continue

            checkpoint = self._load_path(path)

            if checkpoint.job_id != job_id:
                raise PipelineCheckpointCorruptError(
                    "Persisted checkpoint job ID does "
                    "not match its storage location."
                )

            expected_name = f"{checkpoint.checkpoint_id}" f"{self.FILE_SUFFIX}"

            if path.name != expected_name:
                raise PipelineCheckpointCorruptError(
                    "Persisted checkpoint ID does not " "match its filename."
                )

            checkpoints.append(checkpoint)

        return sorted(
            checkpoints,
            key=lambda checkpoint: (
                checkpoint.created_at,
                str(checkpoint.checkpoint_id),
            ),
        )

    def delete(
        self,
        *,
        job_id: UUID,
        checkpoint_id: UUID,
    ) -> bool:
        """
        Delete one persisted checkpoint.

        Returns False when the checkpoint does not exist.
        """

        path = self._job_directory(job_id) / f"{checkpoint_id}{self.FILE_SUFFIX}"

        if not path.exists():
            return False

        if not path.is_file():
            raise PipelineCheckpointStorageError(
                "Checkpoint storage path is not a file."
            )

        try:
            path.unlink()
        except OSError as error:
            raise PipelineCheckpointStorageError(
                "Checkpoint could not be deleted."
            ) from error

        return True

    def _checkpoint_path(
        self,
        checkpoint: PipelineCheckpoint,
    ) -> Path:
        """Build the canonical path for one checkpoint."""

        return self._job_directory(checkpoint.job_id) / (
            f"{checkpoint.checkpoint_id}" f"{self.FILE_SUFFIX}"
        )

    def _job_directory(
        self,
        job_id: UUID,
    ) -> Path:
        """Build the canonical directory for one job."""

        return self.storage_root / str(job_id)

    @staticmethod
    def _load_path(
        path: Path,
    ) -> PipelineCheckpoint:
        """Load and validate one checkpoint file."""

        try:
            raw_text = path.read_text(
                encoding="utf-8",
            )
        except OSError as error:
            raise PipelineCheckpointStorageError(
                "Checkpoint file could not be read."
            ) from error

        try:
            payload: Any = json.loads(raw_text)
        except json.JSONDecodeError as error:
            raise PipelineCheckpointCorruptError(
                "Checkpoint file contains invalid JSON."
            ) from error

        if not isinstance(
            payload,
            dict,
        ):
            raise PipelineCheckpointCorruptError(
                "Checkpoint JSON root must be an object."
            )

        try:
            return PipelineCheckpoint.model_validate(payload)
        except ValidationError as error:
            raise PipelineCheckpointCorruptError(
                "Checkpoint file does not satisfy " "the PipelineCheckpoint schema."
            ) from error

    @staticmethod
    def _atomic_write_json(
        *,
        destination: Path,
        payload: dict[str, Any],
    ) -> None:
        """Write JSON through a temporary file and atomic replace."""

        temporary_path: Path | None = None

        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=destination.parent,
                prefix=(f".{destination.stem}."),
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                json.dump(
                    payload,
                    temporary_file,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )

                temporary_file.write("\n")

                temporary_file.flush()

                os.fsync(temporary_file.fileno())

                temporary_path = Path(temporary_file.name)

            temporary_path.replace(destination)

        except (
            OSError,
            TypeError,
            ValueError,
        ) as error:
            raise PipelineCheckpointStorageError(
                "Checkpoint could not be persisted."
            ) from error

        finally:
            if temporary_path is not None and temporary_path.exists():
                try:
                    temporary_path.unlink()
                except OSError:
                    pass
