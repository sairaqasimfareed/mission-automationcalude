from __future__ import annotations

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from src.models.asset_index import (
    AssetIndex,
    IndexedAssetSource,
)
from src.models.asset_state import (
    AssetCandidate,
    AssetUserDecision,
)
from src.models.media_strategy import (
    SceneSourceStatus,
    SceneSourceType,
)
from src.models.scene import (
    Scene,
    SceneStatus,
)
from src.models.video_clip import (
    VideoClipStatus,
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


class FakeDownloadStream(BytesIO):
    """In-memory stock download response."""

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


stock_content = b"approved-stock-video"


def successful_opener(
    source_url: str,
    timeout_seconds: float,
) -> FakeDownloadStream:
    assert source_url.endswith(".mp4")
    assert timeout_seconds > 0

    return FakeDownloadStream(
        stock_content
    )


scene = Scene(
    scene_number=1,
    title="Roman Soldiers",
    narration=(
        "Roman soldiers march through "
        "the ancient city."
    ),
    visual_prompt=(
        "Roman soldiers marching"
    ),
    stock_query=(
        "Roman soldiers marching"
    ),
    estimated_duration_seconds=8,
    source_type=(
        SceneSourceType.STOCK_FOOTAGE
    ),
    status=SceneStatus.READY,
)


approved_candidate = AssetCandidate(
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
    tags=[
        "roman",
        "soldiers",
    ],
    metadata={
        "user_decision": (
            AssetUserDecision.USE_STOCK.value
        ),
    },
)


with TemporaryDirectory() as temporary_directory:
    root = Path(temporary_directory)

    asset_index = AssetIndex()

    download_service = StockDownloadService(
        temporary_directory=(
            root / "temporary-downloads"
        ),
        maximum_file_size_bytes=1024,
        timeout_seconds=10.0,
        opener=successful_opener,
    )

    storage_service = StockAssetStorageService(
        storage_root=(
            root / "project-assets"
        ),
        asset_index=asset_index,
    )

    service = StockAcquisitionService(
        download_service=download_service,
        storage_service=storage_service,
    )

    result = service.acquire(
        scene=scene,
        candidate=approved_candidate,
        project_id="history-project",
    )

    print(
        "Acquisition success:",
        result.success,
    )

    assert result.success is True
    assert result.clip is not None
    assert result.indexed_asset is not None
    assert result.reused_existing is False

    clip = result.clip
    indexed_asset = result.indexed_asset

    assert clip.status == VideoClipStatus.READY

    assert (
        clip.source_status
        == SceneSourceStatus.READY
    )

    assert (
        clip.source_type
        == SceneSourceType.STOCK_FOOTAGE
    )

    assert clip.provider == "Pexels"
    assert clip.source_url is not None
    assert clip.local_file is not None

    stored_path = Path(
        clip.local_file
    )

    assert stored_path.exists()
    assert stored_path.read_bytes() == stock_content

    assert (
        indexed_asset.source
        == IndexedAssetSource.STOCK
    )

    assert len(asset_index.assets) == 1

    duplicate_result = service.acquire(
        scene=scene,
        candidate=approved_candidate,
        project_id="history-project",
    )

    assert duplicate_result.success is True
    assert duplicate_result.clip is not None
    assert duplicate_result.reused_existing is True

    assert len(asset_index.assets) == 1

    assert any(
        "reused" in warning.lower()
        for warning in duplicate_result.warnings
    )


with TemporaryDirectory() as temporary_directory:
    root = Path(temporary_directory)

    validation_service = StockAcquisitionService(
        download_service=StockDownloadService(
            temporary_directory=(
                root / "temporary-downloads"
            ),
            opener=successful_opener,
        ),
        storage_service=StockAssetStorageService(
            storage_root=root / "storage",
            asset_index=AssetIndex(),
        ),
    )

    unapproved_candidate = (
        approved_candidate.model_copy(
            update={
                "approved": False,
            }
        )
    )

    unapproved_result = (
        validation_service.acquire(
            scene=scene,
            candidate=unapproved_candidate,
            project_id="history-project",
        )
    )

    assert unapproved_result.success is False
    assert unapproved_result.failure is not None

    wrong_source_candidate = (
        approved_candidate.model_copy(
            update={
                "source_type": (
                    SceneSourceType.LOCAL_LIBRARY
                ),
            }
        )
    )

    wrong_source_result = (
        validation_service.acquire(
            scene=scene,
            candidate=wrong_source_candidate,
            project_id="history-project",
        )
    )

    assert wrong_source_result.success is False
    assert wrong_source_result.failure is not None

    missing_url_candidate = (
        approved_candidate.model_copy(
            update={
                "source_url": None,
            }
        )
    )

    missing_url_result = (
        validation_service.acquire(
            scene=scene,
            candidate=missing_url_candidate,
            project_id="history-project",
        )
    )

    assert missing_url_result.success is False
    assert missing_url_result.failure is not None


def failing_opener(
    source_url: str,
    timeout_seconds: float,
) -> FakeDownloadStream:
    raise ConnectionError(
        "Stock provider unavailable."
    )


with TemporaryDirectory() as temporary_directory:
    root = Path(temporary_directory)

    failure_service = StockAcquisitionService(
        download_service=StockDownloadService(
            temporary_directory=(
                root / "temporary-downloads"
            ),
            opener=failing_opener,
        ),
        storage_service=StockAssetStorageService(
            storage_root=root / "storage",
            asset_index=AssetIndex(),
        ),
    )

    failure_result = failure_service.acquire(
        scene=scene,
        candidate=approved_candidate,
        project_id="history-project",
    )

    assert failure_result.success is False
    assert failure_result.failure is not None

    assert (
        failure_result.failure.module_name
        == "stock_download"
    )

    assert (
        failure_result.failure.requires_user_decision
        is True
    )


print(
    "Stock Acquisition Service tests "
    "completed successfully."
)