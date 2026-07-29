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


class ImageToVideoProvider(VisualSourceProvider):
    """
    Dry-run Image-to-Video provider.

    A real image-to-video API can replace this implementation later.
    """

    supported_source_type = SceneSourceType.IMAGE_TO_VIDEO

    @property
    def provider_name(self) -> str:
        return "Image-to-Video Provider"

    def health_check(self) -> bool:
        return True

    def supports(self, scene: Scene) -> bool:
        return (
            scene.source_type
            == self.supported_source_type
        )

    def acquire(self, scene: Scene) -> VideoClip:
        prompt = scene.image_prompt or scene.visual_prompt

        return VideoClip(
            scene_number=scene.scene_number,
            source_type=SceneSourceType.IMAGE_TO_VIDEO,
            duration_seconds=scene.estimated_duration_seconds,
            prompt=prompt,
            provider=self.provider_name,
            local_file=(
                "outputs/image_to_video/"
                f"scene_{scene.scene_number:03}.mp4"
            ),
            source_status=SceneSourceStatus.READY,
            status=VideoClipStatus.READY,
            warnings=[
                "Dry-run provider: no real video file was generated."
            ],
        )