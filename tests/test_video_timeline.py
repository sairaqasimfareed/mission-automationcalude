from src.models.media_strategy import SceneSourceType
from src.models.video_clip import (
    VideoClip,
    VideoClipStatus,
)
from src.models.video_timeline import VideoTimeline

clip1 = VideoClip(
    scene_number=1,
    source_type=SceneSourceType.MANUAL_UPLOAD,
    prompt="Scene 1",
    duration_seconds=8,
    provider="Manual Upload",
    local_file="assets/videos/manual/scene_001.mp4",
    status=VideoClipStatus.READY,
)

clip2 = VideoClip(
    scene_number=2,
    source_type=SceneSourceType.STOCK_FOOTAGE,
    prompt="Scene 2",
    duration_seconds=8,
    provider="Pexels",
    source_url="https://example.com/scene_002.mp4",
    status=VideoClipStatus.READY,
)

clip3 = VideoClip(
    scene_number=3,
    source_type=SceneSourceType.LOCAL_LIBRARY,
    prompt="Scene 3",
    duration_seconds=10,
    provider="Local Library",
    local_file="assets/videos/local/scene_003.mp4",
    status=VideoClipStatus.READY,
)

timeline = VideoTimeline(
    clips=[
        clip1,
        clip2,
        clip3,
    ]
)

duration = timeline.calculate_duration()

print("Clips:", len(timeline.clips))
print("Duration:", duration)
print("Resolution:", timeline.output_resolution)
print("FPS:", timeline.frame_rate)

assert duration == 26
assert len(timeline.clips) == 3

print("Video Timeline tests completed successfully.")
