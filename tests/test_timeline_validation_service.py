from __future__ import annotations

from src.models.media_strategy import (
    SceneSourceStatus,
    SceneSourceType,
)
from src.models.timeline_validation import (
    TimelineValidationCode,
)
from src.models.video_clip import (
    VideoClip,
    VideoClipStatus,
)
from src.models.video_timeline import VideoTimeline
from src.models.video_timeline_item import (
    VideoTimelineItem,
)
from src.services.timeline_builder_service import (
    TimelineBuilderService,
)
from src.services.timeline_validation_service import (
    TimelineValidationService,
)


def build_clip(
    *,
    scene_number: int,
    duration_seconds: int,
) -> VideoClip:
    return VideoClip(
        scene_number=scene_number,
        source_type=(SceneSourceType.MANUAL_UPLOAD),
        duration_seconds=duration_seconds,
        prompt=f"Scene {scene_number}",
        provider="Manual Upload",
        local_file=("assets/videos/manual/" f"scene_{scene_number:03}.mp4"),
        source_status=SceneSourceStatus.READY,
        status=VideoClipStatus.READY,
    )


clips = [
    build_clip(
        scene_number=1,
        duration_seconds=8,
    ),
    build_clip(
        scene_number=2,
        duration_seconds=8,
    ),
    build_clip(
        scene_number=3,
        duration_seconds=10,
    ),
]

builder = TimelineBuilderService()
validator = TimelineValidationService()

valid_timeline = builder.build(clips)

valid_result = validator.validate(valid_timeline)

print("Valid timeline:", valid_result.is_valid)
print("Items:", valid_result.enabled_item_count)
print(
    "Duration:",
    valid_result.total_duration_seconds,
)

assert valid_result.is_valid is True
assert valid_result.issue_count == 0
assert valid_result.enabled_item_count == 3
assert valid_result.track_count == 1
assert valid_result.total_duration_seconds == 26.0


gap_timeline = VideoTimeline(
    clips=clips,
    items=[
        VideoTimelineItem(
            clip=clips[0],
            scene_number=1,
            start_time_seconds=0.0,
            end_time_seconds=8.0,
        ),
        VideoTimelineItem(
            clip=clips[1],
            scene_number=2,
            start_time_seconds=10.0,
            end_time_seconds=18.0,
        ),
    ],
)

gap_result = validator.validate(gap_timeline)

assert gap_result.is_valid is False
assert gap_result.gap_duration_seconds == 2.0

assert any(
    issue.code == TimelineValidationCode.TIMELINE_GAP for issue in gap_result.errors
)


overlap_timeline = VideoTimeline(
    clips=clips,
    items=[
        VideoTimelineItem(
            clip=clips[0],
            scene_number=1,
            start_time_seconds=0.0,
            end_time_seconds=8.0,
        ),
        VideoTimelineItem(
            clip=clips[1],
            scene_number=2,
            start_time_seconds=6.0,
            end_time_seconds=14.0,
        ),
    ],
)

overlap_result = validator.validate(overlap_timeline)

assert overlap_result.is_valid is False
assert overlap_result.overlap_duration_seconds == 2.0

assert any(
    issue.code == TimelineValidationCode.TIMELINE_OVERLAP
    for issue in overlap_result.errors
)


duplicate_timeline = VideoTimeline(
    clips=[
        clips[0],
    ],
    items=[
        VideoTimelineItem(
            clip=clips[0],
            scene_number=1,
            start_time_seconds=0.0,
            end_time_seconds=8.0,
        ),
        VideoTimelineItem(
            clip=clips[0],
            scene_number=1,
            start_time_seconds=8.0,
            end_time_seconds=16.0,
        ),
    ],
)

duplicate_result = validator.validate(duplicate_timeline)

assert duplicate_result.is_valid is False

assert any(
    issue.code == TimelineValidationCode.DUPLICATE_SCENE
    for issue in duplicate_result.errors
)


empty_timeline = VideoTimeline()

empty_result = validator.validate(empty_timeline)

assert empty_result.is_valid is False

assert any(
    issue.code == TimelineValidationCode.NO_ITEMS for issue in empty_result.errors
)


disabled_timeline = VideoTimeline(
    clips=[
        clips[0],
    ],
    items=[
        VideoTimelineItem(
            clip=clips[0],
            scene_number=1,
            start_time_seconds=0.0,
            end_time_seconds=8.0,
            enabled=False,
        )
    ],
)

disabled_result = validator.validate(disabled_timeline)

assert disabled_result.is_valid is False
assert disabled_result.enabled_item_count == 0


print("Timeline Validation Service tests " "completed successfully.")
