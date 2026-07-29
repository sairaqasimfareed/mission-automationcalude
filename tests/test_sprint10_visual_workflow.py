from src.models.asset_index import (
    AssetIndex,
    IndexedAsset,
    IndexedAssetSource,
    IndexedAssetType,
)
from src.models.asset_state import (
    AssetUserDecision,
    AssetWorkflowStatus,
)
from src.models.media_strategy import (
    SceneSourceStatus,
    SceneSourceType,
)
from src.models.scene import Scene, SceneStatus
from src.models.video_clip import (
    VideoClip,
    VideoClipStatus,
)
from src.providers.visual_source_provider import VisualSourceProvider
from src.services.asset_decision_service import AssetDecisionService
from src.services.asset_manager import AssetManager
from src.services.local_asset_search_service import (
    LocalAssetSearchService,
)
from src.services.visual_asset_router import VisualAssetRouter


class DummyLocalLibraryProvider(VisualSourceProvider):
    supported_source_type = SceneSourceType.LOCAL_LIBRARY

    @property
    def provider_name(self) -> str:
        return "Local Library Provider"

    def health_check(self) -> bool:
        return True

    def supports(self, scene: Scene) -> bool:
        return (
            scene.source_type
            == self.supported_source_type
        )

    def acquire(self, scene: Scene) -> VideoClip:
        if not scene.selected_asset_path:
            raise ValueError(
                "Local library asset path is missing."
            )

        return VideoClip(
            scene_number=scene.scene_number,
            source_type=SceneSourceType.LOCAL_LIBRARY,
            duration_seconds=scene.estimated_duration_seconds,
            prompt=scene.visual_prompt,
            provider=self.provider_name,
            local_file=scene.selected_asset_path,
            source_status=SceneSourceStatus.READY,
            status=VideoClipStatus.READY,
        )


asset_index = AssetIndex(
    assets=[
        IndexedAsset(
            asset_type=IndexedAssetType.VIDEO,
            source=IndexedAssetSource.LOCAL_LIBRARY,
            file_path=(
                "assets/videos/local/"
                "ancient_tunnel.mp4"
            ),
            title="Ancient Underground Tunnel",
            provider="Local Library",
            license_type="owned",
            duration_seconds=8,
            resolution="3840x2160",
            aspect_ratio="16:9",
            tags=[
                "ancient",
                "underground",
                "tunnel",
            ],
            keywords=[
                "hidden city",
            ],
        )
    ]
)

scene = Scene(
    scene_number=1,
    title="Hidden Underground City",
    narration="Opening narration",
    visual_prompt="Ancient underground tunnel",
    estimated_duration_seconds=8,
    status=SceneStatus.READY,
)

search_service = LocalAssetSearchService(asset_index)
asset_manager = AssetManager(search_service)

state = asset_manager.search_local_assets(scene)

print("Search status:", state.status)
print("Local results:", len(state.local_candidates))

assert (
    state.status
    == AssetWorkflowStatus.LOCAL_RESULTS_AVAILABLE
)
assert len(state.local_candidates) == 1

decision_service = AssetDecisionService()

state = decision_service.apply_decision(
    state=state,
    decision=AssetUserDecision.USE_LOCAL,
    selected_candidate_index=0,
)

assert state.selected_candidate is not None
assert state.selected_candidate.file_path is not None

scene.source_type = SceneSourceType.LOCAL_LIBRARY
scene.local_library_query = scene.visual_prompt
scene.selected_asset_path = (
    state.selected_candidate.file_path
)

router = VisualAssetRouter(
    providers=[
        DummyLocalLibraryProvider(),
    ]
)

clip = router.acquire(scene)

print("Selected source:", clip.source_type)
print("Provider:", clip.provider)
print("Clip:", clip.local_file)

assert clip.status == VideoClipStatus.READY
assert (
    clip.source_type
    == SceneSourceType.LOCAL_LIBRARY
)
assert clip.local_file == (
    "assets/videos/local/ancient_tunnel.mp4"
)

print(
    "Sprint 10 Visual Workflow "
    "completed successfully."
)