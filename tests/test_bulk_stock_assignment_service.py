from __future__ import annotations

from pathlib import Path

import pytest

from src.models.asset_index import AssetIndex
from src.models.bulk_stock_assignment import BulkStockAssignmentEntryStatus
from src.models.scene import Scene, SceneStatus
from src.models.video_job import VideoJob
from src.providers.dry_run_stock_download_opener import dry_run_stock_download_opener
from src.providers.stock_footage_provider import StockFootageProvider
from src.services.asset_decision_service import AssetDecisionService
from src.services.asset_manager import AssetManager
from src.services.asset_search_service import AssetSearchService
from src.services.bulk_stock_assignment_service import BulkStockAssignmentService
from src.services.local_asset_search_service import LocalAssetSearchService
from src.services.scene_asset_workflow_service import SceneAssetWorkflowService
from src.services.stock_acquisition_service import StockAcquisitionService
from src.services.stock_asset_storage_service import StockAssetStorageService
from src.services.stock_download_service import StockDownloadService
from src.services.stock_search_service import DryRunStockProvider, StockSearchService
from src.services.visual_asset_router import VisualAssetRouter


def _workflow_service(tmp_path: Path) -> SceneAssetWorkflowService:
    asset_search_service = AssetSearchService(
        stock_search_service=StockSearchService(providers=[DryRunStockProvider()])
    )

    router = VisualAssetRouter(
        providers=[
            StockFootageProvider(
                asset_search_service=asset_search_service,
                stock_acquisition_service=StockAcquisitionService(
                    download_service=StockDownloadService(
                        temporary_directory=tmp_path / "downloads",
                        opener=dry_run_stock_download_opener,
                    ),
                    storage_service=StockAssetStorageService(
                        storage_root=tmp_path / "storage",
                        asset_index=AssetIndex(),
                    ),
                ),
            ),
        ],
    )

    return SceneAssetWorkflowService(
        asset_manager=AssetManager(LocalAssetSearchService(AssetIndex())),
        decision_service=AssetDecisionService(),
        asset_search_service=asset_search_service,
        visual_asset_router=router,
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


def test_assign_resolves_stock_footage_for_every_selected_scene(tmp_path: Path) -> None:
    job = _job(_scene(1), _scene(2))
    service = BulkStockAssignmentService(
        asset_workflow_service=_workflow_service(tmp_path)
    )

    result = service.assign(job=job, scene_numbers=[1, 2])

    assert result.assigned_count == 2
    assert result.failed_count == 0
    assert len(job.video_clips) == 2
    assert {clip.scene_number for clip in job.video_clips} == {1, 2}


def test_assign_only_touches_the_requested_scenes(tmp_path: Path) -> None:
    job = _job(_scene(1), _scene(2), _scene(3))
    service = BulkStockAssignmentService(
        asset_workflow_service=_workflow_service(tmp_path)
    )

    result = service.assign(job=job, scene_numbers=[2])

    assert result.assigned_count == 1
    assert result.entries[0].scene_number == 2
    assert len(job.video_clips) == 1
    assert job.video_clips[0].scene_number == 2


def test_assign_reports_a_scene_not_in_the_project(tmp_path: Path) -> None:
    job = _job(_scene(1))
    service = BulkStockAssignmentService(
        asset_workflow_service=_workflow_service(tmp_path)
    )

    result = service.assign(job=job, scene_numbers=[1, 9])

    failed = [
        entry
        for entry in result.entries
        if entry.status == BulkStockAssignmentEntryStatus.FAILED
    ]
    assert len(failed) == 1
    assert failed[0].scene_number == 9
    assert "No scene 9" in failed[0].detail


def test_assign_skips_a_locked_scene(tmp_path: Path) -> None:
    job = _job(_scene(1, source_locked=True))
    service = BulkStockAssignmentService(
        asset_workflow_service=_workflow_service(tmp_path)
    )

    result = service.assign(job=job, scene_numbers=[1])

    assert result.entries[0].status == BulkStockAssignmentEntryStatus.FAILED
    assert "locked" in result.entries[0].detail.lower()
    assert job.video_clips == []


def test_assign_raises_on_empty_scene_number_list(tmp_path: Path) -> None:
    job = _job(_scene(1))
    service = BulkStockAssignmentService(
        asset_workflow_service=_workflow_service(tmp_path)
    )

    with pytest.raises(ValueError, match="At least one scene number"):
        service.assign(job=job, scene_numbers=[])


def test_assign_selects_the_top_ranked_candidate(tmp_path: Path) -> None:
    job = _job(_scene(1))
    service = BulkStockAssignmentService(
        asset_workflow_service=_workflow_service(tmp_path)
    )

    service.assign(job=job, scene_numbers=[1])

    state = next(s for s in job.scene_asset_states if s.scene_number == 1)
    assert state.selected_candidate is not None
    assert state.selected_candidate.source_url == state.stock_candidates[0].source_url
