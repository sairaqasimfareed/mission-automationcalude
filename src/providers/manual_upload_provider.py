from __future__ import annotations

from pathlib import Path

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


class ManualUploadProvider(VisualSourceProvider):
    """Validates manually uploaded video clips."""

    supported_source_type = SceneSourceType.MANUAL_UPLOAD

    @property
    def provider_name(self) -> str:
        return "Manual Upload Provider"

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

        if not scene.manual_file_path:
            raise ValueError(
                "Manual upload path is missing."
            )

        file_path = Path(scene.manual_file_path)

        if not file_path.exists():
            raise FileNotFoundError(
                f"File not found: {file_path}"
            )

        return VideoClip(
            scene_number=scene.scene_number,
            source_type=scene.source_type,
            duration_seconds=scene.estimated_duration_seconds,
            prompt=scene.visual_prompt,
            provider=self.provider_name,
            local_file=str(file_path),
            source_status=SceneSourceStatus.READY,
            status=VideoClipStatus.READY,
        )