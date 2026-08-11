from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from src.models.thumbnail import (
    ThumbnailConcept,
    ThumbnailImageSourceType,
    ThumbnailLayout,
)
from src.services.thumbnail.thumbnail_artifact_storage_service import (
    ThumbnailArtifactStorageService,
)


def _concept() -> ThumbnailConcept:
    return ThumbnailConcept(
        concept_summary="A diver facing a giant squid.",
        hook_text="GIANT SQUID",
        visual_prompt="A deep sea diver facing a giant squid.",
    )


def _layout() -> ThumbnailLayout:
    return ThumbnailLayout(width=1280, height=720)


def test_store_handles_dry_run_uri_paths_without_touching_disk(
    tmp_path: Path,
) -> None:
    service = ThumbnailArtifactStorageService(storage_root=tmp_path / "storage")

    artifact = service.store(
        source_file_path="dry-run://thumbnail/1280x720.png",
        video_job_id=uuid4(),
        project_id="deep-sea-doc",
        concept=_concept(),
        layout=_layout(),
        image_source_type=ThumbnailImageSourceType.AI_GENERATED,
        provider_name="dry_run",
    )

    assert artifact.file_path == "dry-run://thumbnail/1280x720.png"
    assert artifact.file_size_bytes == 0
    assert artifact.content_hash is None
    assert artifact.warnings


def test_store_copies_a_real_file_into_project_storage(
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "source.png"
    source_file.write_bytes(b"fake-image-bytes")

    service = ThumbnailArtifactStorageService(storage_root=tmp_path / "storage")

    artifact = service.store(
        source_file_path=str(source_file),
        video_job_id=uuid4(),
        project_id="deep-sea-doc",
        concept=_concept(),
        layout=_layout(),
        image_source_type=ThumbnailImageSourceType.AI_GENERATED,
        provider_name="local_upload",
    )

    stored_path = Path(artifact.file_path)

    assert stored_path.exists()
    assert stored_path != source_file
    assert source_file.exists()  # copied, not moved
    assert artifact.file_size_bytes == len(b"fake-image-bytes")
    assert artifact.content_hash is not None
    assert "storage" in str(stored_path)
    assert "deep-sea-doc" in str(stored_path)


def test_store_raises_when_source_file_is_missing(tmp_path: Path) -> None:
    service = ThumbnailArtifactStorageService(storage_root=tmp_path / "storage")

    with pytest.raises(FileNotFoundError):
        service.store(
            source_file_path=str(tmp_path / "missing.png"),
            video_job_id=uuid4(),
            project_id="deep-sea-doc",
            concept=_concept(),
            layout=_layout(),
            image_source_type=ThumbnailImageSourceType.AI_GENERATED,
            provider_name="local_upload",
        )


def test_store_raises_when_source_path_is_a_directory(tmp_path: Path) -> None:
    source_directory = tmp_path / "a_directory"
    source_directory.mkdir()

    service = ThumbnailArtifactStorageService(storage_root=tmp_path / "storage")

    with pytest.raises(ValueError, match="not a file"):
        service.store(
            source_file_path=str(source_directory),
            video_job_id=uuid4(),
            project_id="deep-sea-doc",
            concept=_concept(),
            layout=_layout(),
            image_source_type=ThumbnailImageSourceType.AI_GENERATED,
            provider_name="local_upload",
        )


def test_store_is_idempotent_for_identical_content(tmp_path: Path) -> None:
    source_file = tmp_path / "source.png"
    source_file.write_bytes(b"identical-content")

    service = ThumbnailArtifactStorageService(storage_root=tmp_path / "storage")

    first = service.store(
        source_file_path=str(source_file),
        video_job_id=uuid4(),
        project_id="deep-sea-doc",
        concept=_concept(),
        layout=_layout(),
        image_source_type=ThumbnailImageSourceType.AI_GENERATED,
        provider_name="local_upload",
    )

    second = service.store(
        source_file_path=str(source_file),
        video_job_id=uuid4(),
        project_id="deep-sea-doc",
        concept=_concept(),
        layout=_layout(),
        image_source_type=ThumbnailImageSourceType.AI_GENERATED,
        provider_name="local_upload",
    )

    assert first.file_path == second.file_path
    assert first.content_hash == second.content_hash


def test_store_sanitizes_project_id_for_the_directory_name(
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "source.png"
    source_file.write_bytes(b"fake-image-bytes")

    service = ThumbnailArtifactStorageService(storage_root=tmp_path / "storage")

    artifact = service.store(
        source_file_path=str(source_file),
        video_job_id=uuid4(),
        project_id="Deep Sea / Doc!",
        concept=_concept(),
        layout=_layout(),
        image_source_type=ThumbnailImageSourceType.AI_GENERATED,
        provider_name="local_upload",
    )

    assert "Deep_Sea" in artifact.file_path
