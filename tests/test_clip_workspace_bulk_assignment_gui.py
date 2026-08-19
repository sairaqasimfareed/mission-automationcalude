from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QCheckBox, QPushButton  # noqa: E402

from src.desktop.job_store import InMemoryJobStore  # noqa: E402
from src.desktop.views.clip_workspace_view import ClipWorkspaceView  # noqa: E402
from src.models.asset_index import AssetIndex  # noqa: E402
from src.models.scene import Scene, SceneStatus  # noqa: E402
from src.models.video_job import VideoJob  # noqa: E402
from src.providers.dry_run_stock_download_opener import (  # noqa: E402
    dry_run_stock_download_opener,
)
from src.providers.stock_footage_provider import StockFootageProvider  # noqa: E402
from src.services.asset_decision_service import AssetDecisionService  # noqa: E402
from src.services.asset_manager import AssetManager  # noqa: E402
from src.services.asset_search_service import AssetSearchService  # noqa: E402
from src.services.local_asset_search_service import (  # noqa: E402
    LocalAssetSearchService,
)
from src.services.scene_asset_workflow_service import (  # noqa: E402
    SceneAssetWorkflowService,
)
from src.services.stock_acquisition_service import StockAcquisitionService  # noqa: E402
from src.services.stock_asset_storage_service import (  # noqa: E402
    StockAssetStorageService,
)
from src.services.stock_download_service import StockDownloadService  # noqa: E402
from src.services.stock_search_service import (  # noqa: E402
    DryRunStockProvider,
    StockSearchService,
)
from src.services.visual_asset_router import VisualAssetRouter  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])

    yield app  # type: ignore[misc]


@pytest.fixture(autouse=True)
def no_blocking_dialogs(monkeypatch: pytest.MonkeyPatch) -> None:
    # QMessageBox.information()/.warning() open a real modal dialog and
    # block forever under the offscreen Qt platform (no display to
    # dismiss it) - same guard test_desktop_app_integration.py's
    # fixture applies for every other view that shows one.
    monkeypatch.setattr(
        "src.desktop.views.clip_workspace_view.QMessageBox.information",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "src.desktop.views.clip_workspace_view.QMessageBox.warning",
        lambda *args, **kwargs: None,
    )


def _asset_workflow_service(tmp_path: Path) -> SceneAssetWorkflowService:
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


def _job() -> VideoJob:
    job = VideoJob(
        project_name="Mary Celeste Documentary",
        channel_name="Maritime Mysteries",
        niche="unsolved maritime disappearances",
        topic="The Mary Celeste",
    )
    job.scenes = [
        Scene(
            scene_number=number,
            title=f"Scene {number}",
            narration="Narration.",
            visual_prompt="A cinematic visual.",
            estimated_duration_seconds=8,
            status=SceneStatus.READY,
        )
        for number in (1, 2, 3)
    ]

    return job


def test_checking_scenes_updates_selection_state(
    qapp: QApplication, tmp_path: Path
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = ClipWorkspaceView(
        job_store=job_store,
        asset_workflow_service=_asset_workflow_service(tmp_path),
        on_change=lambda: None,
    )
    view.set_job(job.id)
    view.refresh(job)

    view._handle_toggle_scene_selection(1, True)
    view._handle_toggle_scene_selection(2, True)

    assert view._selected_scene_numbers == {1, 2}


def _bulk_assign_button(view: ClipWorkspaceView) -> QPushButton:
    # refresh() only detaches old card widgets via deleteLater() - they
    # stay in the QObject tree (and so in findChildren() results) until
    # the event loop actually processes the deferred deletion.
    QApplication.processEvents()

    matches = [
        button
        for button in view.findChildren(QPushButton)
        if "selected scene" in button.text()
    ]

    return matches[-1]


def test_bulk_assign_button_disabled_with_no_selection(
    qapp: QApplication, tmp_path: Path
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = ClipWorkspaceView(
        job_store=job_store,
        asset_workflow_service=_asset_workflow_service(tmp_path),
        on_change=lambda: None,
    )
    view.set_job(job.id)
    view.refresh(job)

    assert len(view.findChildren(QCheckBox)) == 3
    assert _bulk_assign_button(view).isEnabled() is False


def test_bulk_assign_button_enables_once_a_scene_is_selected(
    qapp: QApplication, tmp_path: Path
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = ClipWorkspaceView(
        job_store=job_store,
        asset_workflow_service=_asset_workflow_service(tmp_path),
        on_change=lambda: None,
    )
    view.set_job(job.id)
    view.refresh(job)

    view._handle_toggle_scene_selection(1, True)

    assert _bulk_assign_button(view).isEnabled() is True


def test_bulk_assign_resolves_selected_scenes_and_clears_selection(
    qapp: QApplication, tmp_path: Path
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    changes: list[None] = []
    view = ClipWorkspaceView(
        job_store=job_store,
        asset_workflow_service=_asset_workflow_service(tmp_path),
        on_change=lambda: changes.append(None),
    )
    view.set_job(job.id)
    view.refresh(job)

    view._handle_toggle_scene_selection(1, True)
    view._handle_toggle_scene_selection(3, True)

    view._handle_bulk_assign_stock()

    assert {clip.scene_number for clip in job.video_clips} == {1, 3}
    assert view._selected_scene_numbers == set()
    assert changes


def test_bulk_assign_does_nothing_with_no_selection(
    qapp: QApplication, tmp_path: Path
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = ClipWorkspaceView(
        job_store=job_store,
        asset_workflow_service=_asset_workflow_service(tmp_path),
        on_change=lambda: None,
    )
    view.set_job(job.id)
    view.refresh(job)

    view._handle_bulk_assign_stock()  # must not raise

    assert job.video_clips == []


def test_stale_selection_is_dropped_when_a_scene_no_longer_exists(
    qapp: QApplication, tmp_path: Path
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = ClipWorkspaceView(
        job_store=job_store,
        asset_workflow_service=_asset_workflow_service(tmp_path),
        on_change=lambda: None,
    )
    view.set_job(job.id)
    view.refresh(job)

    view._handle_toggle_scene_selection(1, True)

    job.scenes = [scene for scene in job.scenes if scene.scene_number != 1]
    view.refresh(job)

    assert 1 not in view._selected_scene_numbers
