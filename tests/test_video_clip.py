from src.models.media_strategy import (
    SceneSourceStatus,
    SceneSourceType,
)
from src.models.video_clip import (
    VideoClip,
    VideoClipStatus,
)


clip = VideoClip(
    scene_number=1,
    source_type=SceneSourceType.MANUAL_UPLOAD,
    duration_seconds=8,
    prompt=(
        "Ultra realistic underground city, cinematic lighting, "
        "8K, volumetric fog."
    ),
    provider="Manual Upload",
    local_file="assets/videos/manual/scene_001.mp4",
    source_status=SceneSourceStatus.READY,
    status=VideoClipStatus.READY,
    estimated_cost=0.0,
)

print("Scene:", clip.scene_number)
print("Source:", clip.source_type)
print("Provider:", clip.provider)
print("Status:", clip.status)
print("Output:", clip.local_file)
print("Estimated Cost:", clip.estimated_cost)

assert clip.status == VideoClipStatus.READY
assert clip.source_status == SceneSourceStatus.READY
assert clip.duration_seconds == 8
assert clip.local_file == "assets/videos/manual/scene_001.mp4"

print("Video Clip model tests completed successfully.")