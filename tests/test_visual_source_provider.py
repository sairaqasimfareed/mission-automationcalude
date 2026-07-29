from src.models.media_strategy import (
    SceneSourceStatus,
    SceneSourceType,
)
from src.models.scene import Scene, SceneStatus
from src.models.video_clip import VideoClip, VideoClipStatus
from src.providers.visual_source_provider import VisualSourceProvider


class DummyManualProvider(VisualSourceProvider):

    @property
    def provider_name(self) -> str:
        return "Dummy Manual Provider"

    def health_check(self) -> bool:
        return True

    def supports(self, scene: Scene) -> bool:
        return scene.source_type == SceneSourceType.MANUAL_UPLOAD

    def acquire(self, scene: Scene) -> VideoClip:
        return VideoClip(
            scene_number=scene.scene_number,
            source_type=scene.source_type,
            duration_seconds=scene.estimated_duration_seconds,
            prompt=scene.visual_prompt,
            provider=self.provider_name,
            local_file="assets/videos/manual/scene_001.mp4",
            source_status=SceneSourceStatus.READY,
            status=VideoClipStatus.READY,
        )


scene = Scene(
    scene_number=1,
    title="Manual Clip",
    narration="A hidden city appears beneath the streets.",
    visual_prompt="Cinematic underground city.",
    estimated_duration_seconds=8,
    source_type=SceneSourceType.MANUAL_UPLOAD,
    source_status=SceneSourceStatus.WAITING_FOR_UPLOAD,
    status=SceneStatus.READY,
)

provider = DummyManualProvider()

print("Provider:", provider.provider_name)
print("Healthy:", provider.health_check())
print("Supports scene:", provider.supports(scene))

clip = provider.acquire(scene)

print("Clip source:", clip.source_type)
print("Clip status:", clip.status)
print("Clip file:", clip.local_file)

assert provider.health_check() is True
assert provider.supports(scene) is True
assert clip.status == VideoClipStatus.READY
assert clip.local_file == "assets/videos/manual/scene_001.mp4"

print("Visual Source Provider tests completed successfully.")