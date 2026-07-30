from __future__ import annotations

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from src.models.asset_index import AssetIndex
from src.models.asset_state import AssetCandidate
from src.models.media_strategy import (
    SceneSourceType,
)
from src.models.scene import (
    Scene,
    SceneStatus,
)
from src.models.stock_acquisition_request import (
    StockAcquisitionRequest,
)
from src.models.video_clip import VideoClipStatus
from src.providers.stock_footage_provider import (
    StockFootageProvider,
)
from src.services.asset_search_service import (
    AssetSearchResult,
    AssetSearchService,
    AssetType,
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


class DummyStockSearch(
    AssetSearchService,
):
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
                file_url=(
                    "https://example.com/"
                    "legacy-stock.mp4"
                ),
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
            "Content-Length": str(
                len(content)
            ),
        }


def successful_opener(
    source_url: str,
    timeout_seconds: float,
) -> FakeDownloadStream:
    assert source_url.endswith(".mp4")
    assert timeout_seconds > 0

    return FakeDownloadStream(
        b"router-stock-video"
    )


scene = Scene(
    scene_number=1,
    title="Roman Soldiers",
    narration=(
        "Roman soldiers march through "
        "the ancient city."
    ),
    visual_prompt="Roman soldiers marching",
    stock_query="Roman soldiers marching",
    estimated_duration_seconds=8,
    source_type=SceneSourceType.STOCK_FOOTAGE,
    status=SceneStatus.READY,
)


with TemporaryDirectory() as temporary_directory:
    root = Path(temporary_directory)

    asset_index = AssetIndex()

    acquisition_service = (
        StockAcquisitionService(
            download_service=(
                StockDownloadService(
                    temporary_directory=(
                        root / "downloads"
                    ),
                    opener=successful_opener,
                )
            ),
            storage_service=(
                StockAssetStorageService(
                    storage_root=(
                        root / "storage"
                    ),
                    asset_index=asset_index,
                )
            ),
        )
    )

    stock_provider = StockFootageProvider(
        asset_search_service=(
            DummyStockSearch()
        ),
        stock_acquisition_service=(
            acquisition_service
        ),
    )

    router = VisualAssetRouter(
        providers=[
            stock_provider,
        ]
    )

    assert router.provider_count == 1
    assert router.supports_source(
        SceneSourceType.STOCK_FOOTAGE
    )
    assert router.available_sources() == [
        SceneSourceType.STOCK_FOOTAGE,
    ]

    # Legacy route remains available.
    legacy_clip = router.acquire(
        scene
    )

    assert (
        legacy_clip.status
        == VideoClipStatus.READY
    )
    assert legacy_clip.source_url is not None
    assert legacy_clip.local_file is None

    candidate = AssetCandidate(
        title="Roman Soldiers Marching",
        source_type=(
            SceneSourceType.STOCK_FOOTAGE
        ),
        source_url=(
            "https://example.com/"
            "roman-soldiers.mp4"
        ),
        provider="Pexels",
        provider_asset_id="pexels-001",
        license_type="royalty_free",
        duration_seconds=8,
        resolution="1920x1080",
        aspect_ratio="16:9",
        approved=True,
    )

    request = StockAcquisitionRequest(
        project_id="history-project",
        scene=scene,
        candidate=candidate,
    )

    selected_clip = (
        router.acquire_selected_stock(
            request
        )
    )

    print(
        "Router selected file:",
        selected_clip.local_file,
    )

    assert (
        selected_clip.status
        == VideoClipStatus.READY
    )
    assert selected_clip.local_file is not None
    assert Path(
        selected_clip.local_file
    ).exists()
    assert len(asset_index.assets) == 1


try:
    VisualAssetRouter(
        providers=[],
    ).acquire_selected_stock(
        StockAcquisitionRequest(
            project_id="history-project",
            scene=scene,
            candidate=AssetCandidate(
                title="Approved Candidate",
                source_type=(
                    SceneSourceType
                    .STOCK_FOOTAGE
                ),
                source_url=(
                    "https://example.com/"
                    "candidate.mp4"
                ),
                approved=True,
            ),
        )
    )
except ValueError:
    print(
        "Missing stock provider "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "Router without stock provider should fail."
    )


print(
    "Visual Asset Router Stock Integration "
    "tests completed successfully."
)