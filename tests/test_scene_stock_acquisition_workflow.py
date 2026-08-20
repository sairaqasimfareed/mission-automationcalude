from __future__ import annotations

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from src.models.asset_index import AssetIndex
from src.models.asset_state import (
    AssetCandidate,
    AssetWorkflowStatus,
    SceneAssetState,
)
from src.models.media_strategy import (
    SceneSourceStatus,
    SceneSourceType,
)
from src.models.scene import (
    Scene,
    SceneStatus,
)
from src.models.video_clip import VideoClipStatus
from src.providers.stock_footage_provider import (
    StockFootageProvider,
)
from src.services.asset_decision_service import (
    AssetDecisionService,
)
from src.services.asset_manager import AssetManager
from src.services.asset_search_service import (
    AssetSearchResult,
    AssetSearchService,
    AssetType,
)
from src.services.local_asset_search_service import (
    LocalAssetSearchService,
)
from src.services.scene_asset_workflow_service import (
    SceneAssetWorkflowService,
)
from src.services.stock_acquisition_service import (
    StockAcquisitionService,
)
from src.services.stock_asset_storage_service import (
    StockAssetStorageService,
)
from src.services.stock_download_service import (
    StockDownloadService,
)
from src.services.visual_asset_router import (
    VisualAssetRouter,
)


class DummyStockSearch(AssetSearchService):
    def search(
        self,
        asset_type,
        query,
    ):
        return [
            AssetSearchResult(
                asset_type=AssetType.VIDEO,
                provider="Pexels",
                title=query,
                file_url=("https://example.com/" "roman-soldiers.mp4"),
                license_type="royalty_free",
                duration_seconds=8,
                resolution="1920x1080",
            )
        ]


class FakeDownloadStream(BytesIO):
    def __init__(
        self,
        content: bytes,
    ) -> None:
        super().__init__(content)

        self.headers = {
            "Content-Type": "video/mp4",
            "Content-Length": str(len(content)),
        }


def successful_opener(
    source_url: str,
    timeout_seconds: float,
) -> FakeDownloadStream:
    assert source_url.endswith(".mp4")
    assert timeout_seconds > 0

    return FakeDownloadStream(b"scene-stock-acquisition-video")


scene = Scene(
    scene_number=1,
    title="Roman Soldiers",
    narration=("Roman soldiers march through " "the ancient city."),
    visual_prompt="Roman soldiers marching",
    stock_query="Roman soldiers marching",
    estimated_duration_seconds=8,
    source_type=SceneSourceType.STOCK_FOOTAGE,
    source_status=SceneSourceStatus.PENDING,
    status=SceneStatus.READY,
)


with TemporaryDirectory() as temporary_directory:
    root = Path(temporary_directory)

    asset_index = AssetIndex()

    stock_acquisition_service = StockAcquisitionService(
        download_service=StockDownloadService(
            temporary_directory=(root / "downloads"),
            opener=successful_opener,
        ),
        storage_service=StockAssetStorageService(
            storage_root=(root / "storage"),
            asset_index=asset_index,
        ),
    )

    stock_provider = StockFootageProvider(
        asset_search_service=DummyStockSearch(),
        stock_acquisition_service=(stock_acquisition_service),
    )

    router = VisualAssetRouter(
        providers=[
            stock_provider,
        ]
    )

    workflow = SceneAssetWorkflowService(
        asset_manager=AssetManager(LocalAssetSearchService(AssetIndex())),
        decision_service=AssetDecisionService(),
        asset_search_service=DummyStockSearch(),
        visual_asset_router=router,
    )

    candidate = AssetCandidate(
        title="Roman Soldiers Marching",
        source_type=SceneSourceType.STOCK_FOOTAGE,
        source_url=("https://example.com/" "roman-soldiers.mp4"),
        provider="Pexels",
        provider_asset_id="pexels-001",
        license_type="royalty_free",
        duration_seconds=8,
        resolution="1920x1080",
        aspect_ratio="16:9",
        approved=True,
    )

    state = SceneAssetState(
        scene_id=str(scene.id),
        scene_number=scene.scene_number,
        status=AssetWorkflowStatus.READY,
        selected_source=SceneSourceType.STOCK_FOOTAGE,
        selected_candidate=candidate,
    )

    clip = workflow.acquire_selected_stock(
        scene=scene,
        state=state,
        project_id="history-project",
    )

    print(
        "Workflow stock clip:",
        clip.local_file if clip else None,
    )

    assert clip is not None
    assert clip.status == VideoClipStatus.READY
    assert clip.local_file is not None
    assert Path(clip.local_file).exists()

    assert state.status == AssetWorkflowStatus.READY
    assert state.selected_candidate is not None

    assert scene.source_status == SceneSourceStatus.READY

    assert scene.source_locked is True

    assert scene.selected_asset_path == clip.local_file

    assert len(asset_index.assets) == 1


unconfigured_workflow = SceneAssetWorkflowService(
    asset_manager=AssetManager(LocalAssetSearchService(AssetIndex())),
    decision_service=AssetDecisionService(),
    asset_search_service=DummyStockSearch(),
)

unconfigured_state = SceneAssetState(
    scene_id=str(scene.id),
    scene_number=scene.scene_number,
    status=AssetWorkflowStatus.READY,
    selected_source=SceneSourceType.STOCK_FOOTAGE,
    selected_candidate=AssetCandidate(
        title="Approved Stock",
        source_type=SceneSourceType.STOCK_FOOTAGE,
        source_url=("https://example.com/" "approved-stock.mp4"),
        approved=True,
    ),
)

missing_router_clip = unconfigured_workflow.acquire_selected_stock(
    scene=scene,
    state=unconfigured_state,
    project_id="history-project",
)

assert missing_router_clip is None
assert unconfigured_state.active_failure is not None

assert unconfigured_state.status == AssetWorkflowStatus.WAITING_FOR_RECOVERY_DECISION


print("Scene Stock Acquisition Workflow tests " "completed successfully.")
