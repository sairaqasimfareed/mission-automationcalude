from __future__ import annotations

from src.models.video_clip import (
    VideoClip,
    VideoClipStatus,
)
from src.models.video_timeline import VideoTimeline
from src.models.video_timeline_item import (
    VideoTimelineItem,
)


class TimelineEditingService:
    """Provides basic, provider-independent timeline operations."""

    def enable_scene(
        self,
        timeline: VideoTimeline,
        *,
        scene_number: int,
    ) -> VideoTimelineItem:
        """Enable one timeline item by scene number."""

        item = self._find_item(
            timeline=timeline,
            scene_number=scene_number,
        )

        item.enabled = True
        timeline.calculate_duration()

        return item

    def disable_scene(
        self,
        timeline: VideoTimeline,
        *,
        scene_number: int,
    ) -> VideoTimelineItem:
        """Disable one timeline item without deleting it."""

        item = self._find_item(
            timeline=timeline,
            scene_number=scene_number,
        )

        item.enabled = False
        timeline.calculate_duration()

        return item

    def move_scene(
        self,
        timeline: VideoTimeline,
        *,
        scene_number: int,
        new_start_time_seconds: float,
        track_index: int | None = None,
        layer_index: int | None = None,
    ) -> VideoTimelineItem:
        """
        Move one item while preserving its clip duration.

        Gaps and overlaps are intentionally allowed here and should
        be checked afterwards by TimelineValidationService.
        """

        if new_start_time_seconds < 0:
            raise ValueError("Timeline start time cannot be negative.")

        item = self._find_item(
            timeline=timeline,
            scene_number=scene_number,
        )

        duration = float(item.clip.duration_seconds)

        item.start_time_seconds = new_start_time_seconds

        item.end_time_seconds = new_start_time_seconds + duration

        if track_index is not None:
            if track_index < 0:
                raise ValueError("Timeline track index cannot be negative.")

            item.track_index = track_index

        if layer_index is not None:
            if layer_index < 0:
                raise ValueError("Timeline layer index cannot be negative.")

            item.layer_index = layer_index

        timeline.calculate_duration()

        return item

    def replace_scene_clip(
        self,
        timeline: VideoTimeline,
        *,
        scene_number: int,
        replacement_clip: VideoClip,
    ) -> VideoTimelineItem:
        """
        Replace a timeline clip while preserving its current start time.

        The replacement clip may have a different duration. The item's
        end time and timeline duration are recalculated automatically.
        """

        if replacement_clip.status != VideoClipStatus.READY:
            raise ValueError("Replacement clip must have READY status.")

        if replacement_clip.scene_number != scene_number:
            raise ValueError(
                "Replacement clip scene number must match "
                "the timeline scene being replaced."
            )

        if not replacement_clip.local_file and not replacement_clip.source_url:
            raise ValueError("Replacement clip requires a local file " "or source URL.")

        item = self._find_item(
            timeline=timeline,
            scene_number=scene_number,
        )

        item.clip = replacement_clip

        item.end_time_seconds = item.start_time_seconds + float(
            replacement_clip.duration_seconds
        )

        self._replace_legacy_clip(
            timeline=timeline,
            replacement_clip=replacement_clip,
        )

        timeline.calculate_duration()

        return item

    def remove_scene(
        self,
        timeline: VideoTimeline,
        *,
        scene_number: int,
        remove_legacy_clip: bool = True,
    ) -> VideoTimelineItem:
        """Remove one timeline placement and optionally its legacy clip."""

        item = self._find_item(
            timeline=timeline,
            scene_number=scene_number,
        )

        timeline.items = [
            existing_item
            for existing_item in timeline.items
            if existing_item.id != item.id
        ]

        if remove_legacy_clip:
            timeline.clips = [
                clip for clip in timeline.clips if clip.scene_number != scene_number
            ]

        timeline.calculate_duration()

        return item

    def compact_primary_track(
        self,
        timeline: VideoTimeline,
    ) -> int:
        """
        Remove gaps from enabled primary-track items.

        Disabled items and non-primary tracks are not moved.
        """

        primary_items = sorted(
            (
                item
                for item in timeline.items
                if (item.enabled and item.track_index == 0)
            ),
            key=lambda item: (
                item.start_time_seconds,
                item.scene_number,
            ),
        )

        current_time = 0.0

        for item in primary_items:
            duration = float(item.clip.duration_seconds)

            item.start_time_seconds = current_time
            item.end_time_seconds = current_time + duration

            current_time = item.end_time_seconds

        timeline.calculate_duration()

        return len(primary_items)

    @staticmethod
    def _find_item(
        *,
        timeline: VideoTimeline,
        scene_number: int,
    ) -> VideoTimelineItem:
        """Return one timeline item by scene number."""

        matches = [item for item in timeline.items if item.scene_number == scene_number]

        if not matches:
            raise KeyError("Timeline scene was not found: " f"{scene_number}")

        if len(matches) > 1:
            raise ValueError(
                "Multiple timeline items use the same " f"scene number: {scene_number}"
            )

        return matches[0]

    @staticmethod
    def _replace_legacy_clip(
        *,
        timeline: VideoTimeline,
        replacement_clip: VideoClip,
    ) -> None:
        """Keep the backward-compatible clips list synchronized."""

        replaced = False
        updated_clips: list[VideoClip] = []

        for clip in timeline.clips:
            if clip.scene_number == replacement_clip.scene_number:
                updated_clips.append(replacement_clip)
                replaced = True
            else:
                updated_clips.append(clip)

        if not replaced:
            updated_clips.append(replacement_clip)

        timeline.clips = sorted(
            updated_clips,
            key=lambda clip: clip.scene_number,
        )
