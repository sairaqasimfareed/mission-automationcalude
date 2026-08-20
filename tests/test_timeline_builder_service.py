from __future__ import annotations

from src.models.media_strategy import (
    SceneSourceStatus,
    SceneSourceType,
)
from src.models.video_clip import (
    VideoClip,
    VideoClipStatus,
)
from src.services.timeline_builder_service import (
    TimelineBuilderService,
)

clips = [
    VideoClip(
        scene_number=3,
        source_type=SceneSourceType.LOCAL_LIBRARY,
        duration_seconds=10,
        prompt="Scene 3",
        provider="Local Library",
        local_file=("assets/videos/local/" "scene_003.mp4"),
        source_status=SceneSourceStatus.READY,
        status=VideoClipStatus.READY,
    ),
    VideoClip(
        scene_number=1,
        source_type=SceneSourceType.MANUAL_UPLOAD,
        duration_seconds=8,
        prompt="Scene 1",
        provider="Manual Upload",
        local_file=("assets/videos/manual/" "scene_001.mp4"),
        source_status=SceneSourceStatus.READY,
        status=VideoClipStatus.READY,
    ),
    VideoClip(
        scene_number=2,
        source_type=SceneSourceType.STOCK_FOOTAGE,
        duration_seconds=8,
        prompt="Scene 2",
        provider="Pexels",
        local_file=("assets/videos/stock/" "scene_002.mp4"),
        source_status=SceneSourceStatus.READY,
        status=VideoClipStatus.READY,
    ),
]


service = TimelineBuilderService()

timeline = service.build(
    clips,
    output_resolution="1920x1080",
    frame_rate=30,
)

print("Items:", len(timeline.items))
print("Duration:", timeline.calculate_duration())

assert len(timeline.clips) == 3
assert len(timeline.items) == 3
assert timeline.has_timeline_items is True

assert timeline.clips[0].scene_number == 1
assert timeline.clips[1].scene_number == 2
assert timeline.clips[2].scene_number == 3

assert timeline.items[0].start_time_seconds == 0.0
assert timeline.items[0].end_time_seconds == 8.0

assert timeline.items[1].start_time_seconds == 8.0
assert timeline.items[1].end_time_seconds == 16.0

assert timeline.items[2].start_time_seconds == 16.0
assert timeline.items[2].end_time_seconds == 26.0

assert timeline.calculate_duration() == 26.0


try:
    service.build(
        [
            clips[0],
            clips[0],
        ]
    )
except ValueError:
    print("Duplicate scene number successfully blocked.")
else:
    raise AssertionError("Duplicate scene numbers should fail.")


pending_clip = VideoClip(
    scene_number=4,
    source_type=SceneSourceType.MANUAL_UPLOAD,
    duration_seconds=8,
    prompt="Pending Scene",
    local_file=("assets/videos/manual/" "pending.mp4"),
    status=VideoClipStatus.PENDING,
)

try:
    service.build(
        [
            pending_clip,
        ]
    )
except ValueError:
    print("Pending clip successfully blocked.")
else:
    raise AssertionError("Pending clips should fail.")


print("Timeline Builder Service tests " "completed successfully.")
