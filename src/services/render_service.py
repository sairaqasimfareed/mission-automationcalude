from __future__ import annotations

import time

from src.models.render_result import (
    RenderResult,
    RenderStatus,
)
from src.models.video_timeline import VideoTimeline


class RenderService:
    """
    Dry-run render service.

    FFmpeg integration will replace this implementation later.
    """

    def render(
        self,
        timeline: VideoTimeline,
    ) -> RenderResult:

        start = time.perf_counter()

        time.sleep(0.1)

        elapsed = time.perf_counter() - start

        return RenderResult(
            success=True,
            output_file="outputs/final_video.mp4",
            render_engine="ffmpeg",
            render_time_seconds=elapsed,
            duration_seconds=timeline.calculate_duration(),
            status=RenderStatus.COMPLETED,
        )