from __future__ import annotations

import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Protocol, TypeVar
from uuid import UUID

from pydantic import ValidationError

from src.models.base import MissionBaseModel
from src.models.final_export import FinalExportPackage
from src.models.render_orchestration_result import RenderOrchestrationResult
from src.models.seo import SEOPackage
from src.models.thumbnail import ThumbnailArtifact
from src.models.video_job import VideoJob

_ModelT = TypeVar("_ModelT", bound=MissionBaseModel)


class JobStore(Protocol):
    """Storage interface for desktop projects and their downstream artifacts."""

    def add(self, job: VideoJob) -> None: ...

    def get(self, job_id: UUID) -> VideoJob | None: ...

    def list_all(self) -> list[VideoJob]: ...

    def set_seo_package(self, job_id: UUID, seo_package: SEOPackage) -> None: ...

    def get_seo_package(self, job_id: UUID) -> SEOPackage | None: ...

    def set_thumbnail(self, job_id: UUID, thumbnail: ThumbnailArtifact) -> None: ...

    def get_thumbnail(self, job_id: UUID) -> ThumbnailArtifact | None: ...

    def set_render_result(
        self,
        job_id: UUID,
        render_result: RenderOrchestrationResult,
    ) -> None: ...

    def get_render_result(self, job_id: UUID) -> RenderOrchestrationResult | None: ...

    def set_final_export(
        self, job_id: UUID, final_export: FinalExportPackage
    ) -> None: ...

    def get_final_export(self, job_id: UUID) -> FinalExportPackage | None: ...


class InMemoryJobStore:
    """
    Process-lifetime registry of VideoJobs created through the desktop
    UI.

    This is deliberately not durable persistence - see JsonJobStore
    for the durable equivalent used by the running desktop app. Kept
    for tests and for anything that genuinely wants a scratch store.
    """

    def __init__(self) -> None:
        self._jobs: dict[UUID, VideoJob] = {}
        self._seo_packages: dict[UUID, SEOPackage] = {}
        self._thumbnails: dict[UUID, ThumbnailArtifact] = {}
        self._render_results: dict[UUID, RenderOrchestrationResult] = {}
        self._final_exports: dict[UUID, FinalExportPackage] = {}

    def add(self, job: VideoJob) -> None:
        self._jobs[job.id] = job

    def get(self, job_id: UUID) -> VideoJob | None:
        return self._jobs.get(job_id)

    def list_all(self) -> list[VideoJob]:
        return sorted(
            self._jobs.values(),
            key=lambda job: job.created_at,
            reverse=True,
        )

    def set_seo_package(self, job_id: UUID, seo_package: SEOPackage) -> None:
        self._seo_packages[job_id] = seo_package

    def get_seo_package(self, job_id: UUID) -> SEOPackage | None:
        return self._seo_packages.get(job_id)

    def set_thumbnail(self, job_id: UUID, thumbnail: ThumbnailArtifact) -> None:
        self._thumbnails[job_id] = thumbnail

    def get_thumbnail(self, job_id: UUID) -> ThumbnailArtifact | None:
        return self._thumbnails.get(job_id)

    def set_render_result(
        self,
        job_id: UUID,
        render_result: RenderOrchestrationResult,
    ) -> None:
        self._render_results[job_id] = render_result

    def get_render_result(self, job_id: UUID) -> RenderOrchestrationResult | None:
        return self._render_results.get(job_id)

    def set_final_export(
        self,
        job_id: UUID,
        final_export: FinalExportPackage,
    ) -> None:
        self._final_exports[job_id] = final_export

    def get_final_export(self, job_id: UUID) -> FinalExportPackage | None:
        return self._final_exports.get(job_id)


class JobStoreError(RuntimeError):
    """Raised when persistent desktop project storage is invalid or unavailable."""


class JsonJobStore:
    """
    Durable, file-backed JobStore.

    Each project's VideoJob and its downstream artifacts (SEO package,
    thumbnail, render orchestration result, final export package) are
    stored as separate JSON files named after the job ID, so a write
    to one artifact can never corrupt another - matching
    PipelineCheckpointStorageService's per-concern file layout. Writes
    are atomic (temp file in the same directory, fsync, then replace).

    Every getter is backed by an in-memory cache of the same shape as
    InMemoryJobStore's dicts, populated from disk on first access and
    updated on every write. This is not just a performance cache: it
    is what keeps get()'s reference semantics identical to
    InMemoryJobStore's. VideoJob is mutated in place throughout
    ProjectWorkspaceView's workspace handlers (e.g.
    `job.research = research` in ContentStudioView) rather than
    replaced, then persisted via a later add() call (see
    ProjectWorkspaceView.refresh()) - without the cache, that later
    add(job) would be writing a *different* object than the one a
    fresh disk read would hand back, and the mutation would appear to
    work for the rest of the session but silently never be persisted.
    """

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

        self._jobs: dict[UUID, VideoJob] = {}
        self._seo_packages: dict[UUID, SEOPackage] = {}
        self._thumbnails: dict[UUID, ThumbnailArtifact] = {}
        self._render_results: dict[UUID, RenderOrchestrationResult] = {}
        self._final_exports: dict[UUID, FinalExportPackage] = {}

    def add(self, job: VideoJob) -> None:
        self._jobs[job.id] = job
        self._write(self._job_path(job.id), job)

    def get(self, job_id: UUID) -> VideoJob | None:
        return self._get_cached(
            self._jobs,
            job_id,
            self._job_path(job_id),
            VideoJob,
        )

    def list_all(self) -> list[VideoJob]:
        for path in self.storage_root.glob("*.json"):
            try:
                job_id = UUID(path.stem)
            except ValueError:
                continue

            self.get(job_id)

        return sorted(
            self._jobs.values(),
            key=lambda job: job.created_at,
            reverse=True,
        )

    def set_seo_package(self, job_id: UUID, seo_package: SEOPackage) -> None:
        self._seo_packages[job_id] = seo_package
        self._write(self._artifact_path(job_id, "seo_package"), seo_package)

    def get_seo_package(self, job_id: UUID) -> SEOPackage | None:
        return self._get_cached(
            self._seo_packages,
            job_id,
            self._artifact_path(job_id, "seo_package"),
            SEOPackage,
        )

    def set_thumbnail(self, job_id: UUID, thumbnail: ThumbnailArtifact) -> None:
        self._thumbnails[job_id] = thumbnail
        self._write(self._artifact_path(job_id, "thumbnail"), thumbnail)

    def get_thumbnail(self, job_id: UUID) -> ThumbnailArtifact | None:
        return self._get_cached(
            self._thumbnails,
            job_id,
            self._artifact_path(job_id, "thumbnail"),
            ThumbnailArtifact,
        )

    def set_render_result(
        self,
        job_id: UUID,
        render_result: RenderOrchestrationResult,
    ) -> None:
        self._render_results[job_id] = render_result
        self._write(self._artifact_path(job_id, "render_result"), render_result)

    def get_render_result(self, job_id: UUID) -> RenderOrchestrationResult | None:
        return self._get_cached(
            self._render_results,
            job_id,
            self._artifact_path(job_id, "render_result"),
            RenderOrchestrationResult,
        )

    def set_final_export(
        self,
        job_id: UUID,
        final_export: FinalExportPackage,
    ) -> None:
        self._final_exports[job_id] = final_export
        self._write(self._artifact_path(job_id, "final_export"), final_export)

    def get_final_export(self, job_id: UUID) -> FinalExportPackage | None:
        return self._get_cached(
            self._final_exports,
            job_id,
            self._artifact_path(job_id, "final_export"),
            FinalExportPackage,
        )

    def _get_cached(
        self,
        cache: dict[UUID, _ModelT],
        key: UUID,
        path: Path,
        model_type: type[_ModelT],
    ) -> _ModelT | None:
        if key in cache:
            return cache[key]

        value = self._read(path, model_type)

        if value is not None:
            cache[key] = value

        return value

    def _job_path(self, job_id: UUID) -> Path:
        return self.storage_root / f"{job_id}.json"

    def _artifact_path(self, job_id: UUID, suffix: str) -> Path:
        return self.storage_root / f"{job_id}.{suffix}.json"

    @staticmethod
    def _write(path: Path, model: MissionBaseModel) -> None:
        payload = model.model_dump_json(indent=2)

        temporary_path: Path | None = None

        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=path.parent,
                prefix=f".{path.stem}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                handle.write(payload)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())

                temporary_path = Path(handle.name)

            temporary_path.replace(path)
        except OSError as error:
            raise JobStoreError(f"Unable to persist {path.name}.") from error
        finally:
            if temporary_path is not None and temporary_path.exists():
                try:
                    temporary_path.unlink()
                except OSError:
                    pass

    @staticmethod
    def _read(path: Path, model_type: type[_ModelT]) -> _ModelT | None:
        if not path.exists():
            return None

        try:
            return model_type.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError) as error:
            raise JobStoreError(
                f"Project storage file is invalid: {path.name}."
            ) from error
