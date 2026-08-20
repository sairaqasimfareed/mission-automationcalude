from __future__ import annotations

from src.models.video_clip import (
    VideoClip,
    VideoClipStatus,
)
from src.models.video_timeline import VideoTimeline
from src.models.video_timeline_item import (
    VideoTimelineItem,
)


class TimelineBuilderService:
    """Builds a sequential editing timeline from ready clips."""

    def build(
        self,
        clips: list[VideoClip],
        *,
        output_resolution: str = "1920x1080",
        frame_rate: int = 30,
    ) -> VideoTimeline:
        """Build a gap-free timeline ordered by scene number."""

        if not clips:
            raise ValueError(
                "At least one video clip is required " "to build a timeline."
            )

        if frame_rate < 1:
            raise ValueError("Timeline frame rate must be positive.")

        ordered_clips = sorted(
            clips,
            key=lambda clip: clip.scene_number,
        )

        self._validate_clips(ordered_clips)

        items: list[VideoTimelineItem] = []
        current_time = 0.0

        for clip in ordered_clips:
            end_time = current_time + float(clip.duration_seconds)

            items.append(
                VideoTimelineItem(
                    clip=clip,
                    scene_number=clip.scene_number,
                    start_time_seconds=current_time,
                    end_time_seconds=end_time,
                    track_index=0,
                    layer_index=0,
                )
            )

            current_time = end_time

        timeline = VideoTimeline(
            clips=list(ordered_clips),
            items=items,
            total_duration_seconds=current_time,
            output_resolution=output_resolution,
            frame_rate=frame_rate,
        )

        return timeline

    @staticmethod
    def _validate_clips(
        clips: list[VideoClip],
    ) -> None:
        """Validate clips before timeline placement."""

        scene_numbers: set[int] = set()

        for clip in clips:
            if clip.scene_number in scene_numbers:
                raise ValueError(
                    "Duplicate scene numbers cannot be "
                    "added to the primary video track."
                )

            scene_numbers.add(clip.scene_number)

            if clip.status != VideoClipStatus.READY:
                raise ValueError(
                    "Only READY video clips can be added " "to the editing timeline."
                )

            if clip.duration_seconds <= 0:
                raise ValueError("Timeline clips require a positive duration.")

            if not clip.local_file and not clip.source_url:
                raise ValueError(
                    "Timeline clips require a local file " "or source URL."
                )
