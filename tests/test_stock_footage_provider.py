from src.models.media_strategy import (
    SceneSourceType,
)
from src.models.scene import (
    Scene,
    SceneStatus,
)
from src.models.video_clip import (
    VideoClipStatus,
)
from src.providers.stock_footage_provider import (
    StockFootageProvider,
)
from src.services.asset_search_service import (
    AssetSearchResult,
    AssetSearchService,
    AssetType,
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
                file_url="https://example.com/video.mp4",
                license_type="royalty_free",
                duration_seconds=8,
                resolution="1920x1080",
            )
        ]


scene = Scene(
    scene_number=1,
    title="Opening",
    narration="Opening",
    visual_prompt="Ancient underground tunnel",
    stock_query="Ancient underground tunnel",
    estimated_duration_seconds=8,
    source_type=SceneSourceType.STOCK_FOOTAGE,
    status=SceneStatus.READY,
)

provider = StockFootageProvider(
    DummyStockSearch(),
)

clip = provider.acquire(scene)

print("Provider:", clip.provider)
print("Source:", clip.source_type)
print("Output:", clip.local_file)

assert clip.provider == "Pexels"
assert clip.status == VideoClipStatus.READY

print(
    "Stock Footage Provider tests completed successfully."
)