from __future__ import annotations

from src.models.media_strategy import (
    SceneSourceStatus,
    SceneSourceType,
)
from src.models.scene import Scene
from src.models.stock_acquisition_request import (
    StockAcquisitionRequest,
)
from src.models.video_clip import (
    VideoClip,
    VideoClipStatus,
)
from src.providers.visual_source_provider import (
    VisualSourceProvider,
)
from src.services.asset_search_service import (
    AssetSearchService,
    AssetType,
)
from src.services.stock_acquisition_service import (
    StockAcquisitionService,
)


class StockFootageProvider(VisualSourceProvider):
    """
    Provides stock footage for legacy and approved workflows.

    Legacy workflow:
    - searches stock footage
    - selects the first result
    - returns a URL-backed VideoClip

    Production workflow:
    - accepts an approved StockAcquisitionRequest
    - downloads and stores the selected asset
    - returns a local READY VideoClip
    """

    supported_source_type = (
        SceneSourceType.STOCK_FOOTAGE
    )

    def __init__(
        self,
        asset_search_service: AssetSearchService,
        stock_acquisition_service: (
            StockAcquisitionService | None
        ) = None,
    ) -> None:
        self.asset_search_service = (
            asset_search_service
        )

        self.stock_acquisition_service = (
            stock_acquisition_service
        )

    @property
    def provider_name(self) -> str:
        return "Stock Footage Provider"

    def health_check(self) -> bool:
        return True

    def supports(
        self,
        scene: Scene,
    ) -> bool:
        return (
            scene.source_type
            == self.supported_source_type
        )

    def acquire(
        self,
        scene: Scene,
    ) -> VideoClip:
        """
        Legacy acquisition path.

        This method is retained for backward compatibility.
        New production code should use acquire_selected().
        """

        query = (
            scene.stock_query
            or scene.visual_prompt
        )

        results = (
            self.asset_search_service.search(
                asset_type=AssetType.VIDEO,
                query=query,
            )
        )

        if not results:
            raise ValueError(
                "No stock footage was found."
            )

        asset = results[0]

        return VideoClip(
            scene_number=scene.scene_number,
            source_type=(
                SceneSourceType.STOCK_FOOTAGE
            ),
            duration_seconds=(
                scene.estimated_duration_seconds
            ),
            prompt=query,
            provider=asset.provider,
            source_url=asset.file_url,
            local_file=None,
            license_type=asset.license_type,
            resolution=(
                asset.resolution
                or "1920x1080"
            ),
            source_status=(
                SceneSourceStatus.READY
            ),
            status=VideoClipStatus.READY,
            warnings=[
                (
                    "Legacy stock acquisition returned "
                    "a remote URL. Production workflows "
                    "should use acquire_selected()."
                )
            ],
        )

    def acquire_selected(
        self,
        request: StockAcquisitionRequest,
    ) -> VideoClip:
        """
        Acquire one explicitly approved stock candidate.

        This is the production acquisition path.
        """

        acquisition_service = (
            self.stock_acquisition_service
        )

        if acquisition_service is None:
            raise RuntimeError(
                "Stock acquisition service "
                "is not configured."
            )

        result = acquisition_service.acquire(
            scene=request.scene,
            candidate=request.candidate,
            project_id=request.project_id,
        )

        if not result.success:
            if result.failure is not None:
                raise ValueError(
                    result.failure.message
                )

            raise ValueError(
                "Approved stock asset "
                "could not be acquired."
            )

        if result.clip is None:
            raise ValueError(
                "Stock acquisition succeeded "
                "without returning a video clip."
            )

        return result.clip