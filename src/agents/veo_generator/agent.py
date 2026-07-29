from __future__ import annotations

import time

from src.models.media_strategy import (
    SceneSourceStatus,
    SceneSourceType,
)
from src.models.scene import Scene
from src.models.video_clip import (
    VideoClip,
    VideoClipStatus,
)


class VeoGeneratorAgent:
    """
    Dry-run Google Veo generator.

    Real Veo API integration will replace this implementation later.
    """

    def generate(self, scene: Scene) -> VideoClip:
        """Generate a dry-run video clip for one scene."""

        start = time.perf_counter()

        time.sleep(0.05)

        elapsed = time.perf_counter() - start

        output_file = f"outputs/video/scene_{scene.scene_number:03}.mp4"

        return VideoClip(
            scene_number=scene.scene_number,
            source_type=SceneSourceType.IMAGE_TO_VIDEO,
            duration_seconds=scene.estimated_duration_seconds,
            prompt=scene.visual_prompt,
            provider="Google Veo",
            local_file=output_file,
            acquisition_time_seconds=elapsed,
            estimated_cost=0.0,
            source_status=SceneSourceStatus.READY,
            status=VideoClipStatus.READY,
            metadata={
                "model_name": "veo-3",
                "camera": scene.camera_direction,
                "sound": scene.sound_design,
                "dry_run": True,
                "estimated_cost_credits": 120,
            },
        )
