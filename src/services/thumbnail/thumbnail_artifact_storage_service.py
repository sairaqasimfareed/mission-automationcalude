from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from uuid import UUID

from src.models.thumbnail import (
    ThumbnailArtifact,
    ThumbnailConcept,
    ThumbnailImageSourceType,
    ThumbnailLayout,
)


class ThumbnailArtifactStorageService:
    """
    Store a generated or locally supplied thumbnail image in permanent
    project storage.

    Unlike StockAssetStorageService, thumbnails are not registered in
    the shared AssetIndex: they are not reusable scene visual sources,
    just a per-video packaging deliverable. Deduplication is filesystem-
    based (a content-hash-derived filename), not a shared registry
    lookup, since no shared thumbnail registry exists.

    A source file is copied rather than moved: an AI-generated image is
    typically a disposable temp file, but a locally supplied image
    (LOCAL_UPLOAD / SCENE_FRAME) may be the caller's own file that
    should not be silently deleted from its original location.
    """

    def __init__(self, *, storage_root: str | Path) -> None:
        self.storage_root = Path(storage_root).expanduser().resolve()

        self.storage_root.mkdir(parents=True, exist_ok=True)

    def store(
        self,
        *,
        source_file_path: str,
        video_job_id: UUID,
        project_id: str,
        concept: ThumbnailConcept,
        layout: ThumbnailLayout,
        image_source_type: ThumbnailImageSourceType,
        provider_name: str,
    ) -> ThumbnailArtifact:
        """Store one thumbnail image and return its ThumbnailArtifact."""

        if "://" in source_file_path:
            return ThumbnailArtifact(
                video_job_id=video_job_id,
                concept=concept,
                layout=layout,
                image_source_type=image_source_type,
                provider_name=provider_name,
                file_path=source_file_path,
                file_size_bytes=0,
                content_hash=None,
                warnings=["Dry-run provider: no real thumbnail file was generated."],
            )

        source_file = Path(source_file_path).expanduser().resolve()

        if not source_file.exists():
            raise FileNotFoundError(f"Thumbnail source image not found: {source_file}")

        if not source_file.is_file():
            raise ValueError(f"Thumbnail source path is not a file: {source_file}")

        content_hash = self._hash_file(source_file)

        normalized_project_id = self._sanitize_identifier(project_id)

        project_directory = self.storage_root / normalized_project_id / "thumbnails"

        project_directory.mkdir(parents=True, exist_ok=True)

        extension = source_file.suffix.lower() or ".png"

        destination = project_directory / f"{content_hash[:12]}{extension}"

        if not destination.exists():
            shutil.copy2(str(source_file), str(destination))

        return ThumbnailArtifact(
            video_job_id=video_job_id,
            concept=concept,
            layout=layout,
            image_source_type=image_source_type,
            provider_name=provider_name,
            file_path=str(destination),
            file_size_bytes=destination.stat().st_size,
            content_hash=content_hash,
        )

    @staticmethod
    def _hash_file(file_path: Path) -> str:
        digest = hashlib.sha256()

        with file_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)

        return digest.hexdigest()

    @staticmethod
    def _sanitize_identifier(value: str) -> str:
        normalized = value.strip()

        if not normalized:
            raise ValueError("Project ID cannot be empty.")

        safe_value = "".join(
            character if (character.isalnum() or character in {"-", "_"}) else "_"
            for character in normalized
        )

        return safe_value.strip("_") or "project"
