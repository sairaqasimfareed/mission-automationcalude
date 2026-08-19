from __future__ import annotations

from pathlib import Path

import pytest

from src.models.asset_index import AssetIndex
from src.models.bulk_clip_ingestion import BulkClipIngestionEntryStatus
from src.models.scene import Scene, SceneStatus
from src.models.video_job import VideoJob
from src.services.asset_decision_service import AssetDecisionService
from src.services.asset_manager import AssetManager
from src.services.asset_search_service import AssetSearchService
from src.services.asset_storage_service import AssetStorageService
from src.services.bulk_clip_ingestion_service import BulkClipIngestionService
from src.services.local_asset_search_service import LocalAssetSearchService
from src.services.manual_upload_service import ManualUploadService
from src.services.scene_asset_workflow_service import SceneAssetWorkflowService
from src.services.stock_search_service import DryRunStockProvider, StockSearchService


def _asset_search_service() -> AssetSearchService:
    return AssetSearchService(
        stock_search_service=StockSearchService(providers=[DryRunStockProvider()])
    )


def _workflow_service(tmp_path: Path) -> SceneAssetWorkflowService:
    index = AssetIndex()
    storage_service = AssetStorageService(
        storage_root=tmp_path / "project-assets", asset_index=index
    )
    manual_upload_service = ManualUploadService(
        storage_service=storage_service, maximum_file_size_bytes=10_000
    )

    return SceneAssetWorkflowService(
        asset_manager=AssetManager(LocalAssetSearchService(index)),
        decision_service=AssetDecisionService(),
        asset_search_service=_asset_search_service(),
        manual_upload_service=manual_upload_service,
    )


def _scene(number: int, **overrides: object) -> Scene:
    base: dict[str, object] = dict(
        scene_number=number,
        title=f"Scene {number}",
        narration="Narration.",
        visual_prompt="A cinematic visual.",
        estimated_duration_seconds=8,
        status=SceneStatus.READY,
    )
    base.update(overrides)
    return Scene(**base)


def _job(*scenes: Scene) -> VideoJob:
    job = VideoJob(
        project_name="ocean-project",
        channel_name="Test Channel",
        niche="test niche",
        topic="Test topic",
    )
    job.scenes = list(scenes)
    return job


def test_ingest_assigns_a_matching_file_to_its_scene(tmp_path: Path) -> None:
    source_directory = tmp_path / "inbox"
    source_directory.mkdir()
    (source_directory / "001_scene-1.mp4").write_bytes(b"clip-bytes")

    job = _job(_scene(1))
    service = BulkClipIngestionService(
        asset_workflow_service=_workflow_service(tmp_path)
    )

    result = service.ingest(job=job, source_directory=source_directory)

    assert result.assigned_count == 1
    assert result.entries[0].status == BulkClipIngestionEntryStatus.ASSIGNED
    assert result.entries[0].scene_number == 1
    assert len(job.video_clips) == 1
    assert job.video_clips[0].scene_number == 1
    assert result.scenes_still_missing_a_file == []


def test_ingest_flags_a_file_with_no_leading_scene_number(tmp_path: Path) -> None:
    source_directory = tmp_path / "inbox"
    source_directory.mkdir()
    (source_directory / "final_cut.mp4").write_bytes(b"clip-bytes")

    job = _job(_scene(1))
    service = BulkClipIngestionService(
        asset_workflow_service=_workflow_service(tmp_path)
    )

    result = service.ingest(job=job, source_directory=source_directory)

    assert result.entries[0].status == BulkClipIngestionEntryStatus.NO_MATCHING_SCENE
    assert result.entries[0].scene_number is None
    assert job.video_clips == []


def test_ingest_flags_a_file_matching_no_scene_in_the_project(tmp_path: Path) -> None:
    source_directory = tmp_path / "inbox"
    source_directory.mkdir()
    (source_directory / "005_unknown.mp4").write_bytes(b"clip-bytes")

    job = _job(_scene(1))
    service = BulkClipIngestionService(
        asset_workflow_service=_workflow_service(tmp_path)
    )

    result = service.ingest(job=job, source_directory=source_directory)

    assert result.entries[0].status == BulkClipIngestionEntryStatus.NO_MATCHING_SCENE
    assert result.entries[0].scene_number == 5


def test_ingest_skips_a_locked_scene(tmp_path: Path) -> None:
    source_directory = tmp_path / "inbox"
    source_directory.mkdir()
    (source_directory / "001_scene-1.mp4").write_bytes(b"clip-bytes")

    job = _job(_scene(1, source_locked=True))
    service = BulkClipIngestionService(
        asset_workflow_service=_workflow_service(tmp_path)
    )

    result = service.ingest(job=job, source_directory=source_directory)

    assert result.entries[0].status == BulkClipIngestionEntryStatus.FAILED_VALIDATION
    assert "locked" in result.entries[0].detail.lower()
    assert job.video_clips == []


def test_ingest_reports_scenes_still_missing_a_file(tmp_path: Path) -> None:
    source_directory = tmp_path / "inbox"
    source_directory.mkdir()
    (source_directory / "001_scene-1.mp4").write_bytes(b"clip-bytes")

    job = _job(_scene(1), _scene(2))
    service = BulkClipIngestionService(
        asset_workflow_service=_workflow_service(tmp_path)
    )

    result = service.ingest(job=job, source_directory=source_directory)

    assert result.scenes_still_missing_a_file == [2]


def test_ingest_processes_multiple_files_in_one_batch(tmp_path: Path) -> None:
    source_directory = tmp_path / "inbox"
    source_directory.mkdir()
    (source_directory / "001_scene-1.mp4").write_bytes(b"clip-bytes-1")
    (source_directory / "002_scene-2.mp4").write_bytes(b"clip-bytes-2")
    (source_directory / "003_scene-3.mp4").write_bytes(b"clip-bytes-3")

    job = _job(_scene(1), _scene(2), _scene(3))
    service = BulkClipIngestionService(
        asset_workflow_service=_workflow_service(tmp_path)
    )

    result = service.ingest(job=job, source_directory=source_directory)

    assert result.assigned_count == 3
    assert len(job.video_clips) == 3
    assert result.scenes_still_missing_a_file == []


def test_ingest_raises_when_source_directory_does_not_exist(tmp_path: Path) -> None:
    job = _job(_scene(1))
    service = BulkClipIngestionService(
        asset_workflow_service=_workflow_service(tmp_path)
    )

    with pytest.raises(ValueError, match="is not a directory"):
        service.ingest(job=job, source_directory=tmp_path / "does-not-exist")


def test_ingest_ignores_files_with_unsupported_extensions(tmp_path: Path) -> None:
    source_directory = tmp_path / "inbox"
    source_directory.mkdir()
    (source_directory / "001_notes.txt").write_text("not a video")

    job = _job(_scene(1))
    service = BulkClipIngestionService(
        asset_workflow_service=_workflow_service(tmp_path)
    )

    result = service.ingest(job=job, source_directory=source_directory)

    assert result.entries == []
    assert result.scenes_still_missing_a_file == [1]
