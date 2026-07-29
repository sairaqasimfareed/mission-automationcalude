from __future__ import annotations

from src.models.media_strategy import (
    SceneSourceStatus,
    SceneSourceType,
)
from src.models.scene import Scene
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


class StockFootageProvider(VisualSourceProvider):
    """Provides stock footage after explicit user approval."""

    supported_source_type = SceneSourceType.STOCK_FOOTAGE

    def __init__(
        self,
        asset_search_service: AssetSearchService,
    ) -> None:
        self.asset_search_service = asset_search_service

    @property
    def provider_name(self) -> str:
        return "Stock Footage Provider"

    def health_check(self) -> bool:
        return True

    def supports(
        self,
        scene: Scene,
    ) -> bool:
        return scene.source_type == self.supported_source_type

    def acquire(
        self,
        scene: Scene,
    ) -> VideoClip:

        query = scene.stock_query or scene.visual_prompt

        results = self.asset_search_service.search(
            asset_type=AssetType.VIDEO,
            query=query,
        )

        if not results:
            raise ValueError("No stock footage was found.")

        asset = results[0]

        return VideoClip(
            scene_number=scene.scene_number,
            source_type=SceneSourceType.STOCK_FOOTAGE,
            duration_seconds=scene.estimated_duration_seconds,
            prompt=query,
            provider=asset.provider,
            local_file=asset.file_url,
            source_status=SceneSourceStatus.READY,
            status=VideoClipStatus.READY,
        )
