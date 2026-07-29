from src.models.media_strategy import (
    SceneSourceStatus,
    SceneSourceType,
)
from src.models.scene import Scene, SceneStatus
from src.models.video_clip import VideoClip, VideoClipStatus
from src.providers.visual_source_provider import VisualSourceProvider
from src.services.visual_asset_router import VisualAssetRouter


class ManualProvider(VisualSourceProvider):
    supported_source_type = SceneSourceType.MANUAL_UPLOAD

    @property
    def provider_name(self) -> str:
        return "Manual Provider"

    def health_check(self) -> bool:
        return True

    def supports(self, scene: Scene) -> bool:
        return (
            scene.source_type
            == self.supported_source_type
        )

    def acquire(self, scene: Scene) -> VideoClip:
        return VideoClip(
            scene_number=scene.scene_number,
            source_type=scene.source_type,
            duration_seconds=scene.estimated_duration_seconds,
            prompt=scene.visual_prompt,
            provider=self.provider_name,
            local_file="assets/manual.mp4",
            source_status=SceneSourceStatus.READY,
            status=VideoClipStatus.READY,
        )


router = VisualAssetRouter(
    providers=[
        ManualProvider(),
    ]
)

scene = Scene(
    scene_number=1,
    title="Opening",
    narration="Opening narration",
    visual_prompt="Ancient underground city",
    estimated_duration_seconds=8,
    source_type=SceneSourceType.MANUAL_UPLOAD,
    source_status=SceneSourceStatus.WAITING_FOR_UPLOAD,
    status=SceneStatus.READY,
)

clip = router.acquire(scene)
available_sources = router.available_sources()

print("Provider:", clip.provider)
print("Clip:", clip.local_file)
print("Available sources:", available_sources)

assert clip.provider == "Manual Provider"
assert clip.status == VideoClipStatus.READY
assert available_sources == [
    SceneSourceType.MANUAL_UPLOAD
]

print("Visual Asset Router tests completed successfully.")