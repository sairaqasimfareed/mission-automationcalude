from src.models.video_clip import (
    VideoClip,
    VideoClipStatus,
)
from src.models.video_timeline import VideoTimeline

clip1 = VideoClip(
    scene_number=1,
    prompt="Scene 1",
    duration_seconds=8,
    provider="Google Veo",
    model_name="veo-3",
    status=VideoClipStatus.GENERATED,
)

clip2 = VideoClip(
    scene_number=2,
    prompt="Scene 2",
    duration_seconds=8,
    provider="Google Veo",
    model_name="veo-3",
    status=VideoClipStatus.GENERATED,
)

clip3 = VideoClip(
    scene_number=3,
    prompt="Scene 3",
    duration_seconds=10,
    provider="Google Veo",
    model_name="veo-3",
    status=VideoClipStatus.GENERATED,
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
