from __future__ import annotations

import time

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

        start = time.perf_counter()

        time.sleep(0.05)

        elapsed = time.perf_counter() - start

        return VideoClip(
            scene_number=scene.scene_number,
            prompt=scene.visual_prompt,
            duration_seconds=scene.estimated_duration_seconds,
            provider="Google Veo",
            model_name="veo-3",
            output_file=(
                f"outputs/video/scene_{scene.scene_number:03}.mp4"
            ),
            generation_time_seconds=elapsed,
            cost_credits=120,
            status=VideoClipStatus.GENERATED,
            metadata={
                "camera": scene.camera_direction,
                "sound": scene.sound_design,
            },
        )