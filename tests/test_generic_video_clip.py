from pydantic import ValidationError

from src.models.media_strategy import (
    SceneSourceStatus,
    SceneSourceType,
)
from src.models.video_clip import (
    VideoClip,
    VideoClipStatus,
)

manual_clip = VideoClip(
    scene_number=1,
    source_type=SceneSourceType.MANUAL_UPLOAD,
    duration_seconds=8,
    prompt="Cinematic underground city.",
    provider="Manual Upload",
    local_file="assets/videos/manual/scene_001.mp4",
    source_status=SceneSourceStatus.READY,
    status=VideoClipStatus.READY,
)

stock_clip = VideoClip(
    scene_number=2,
    source_type=SceneSourceType.STOCK_FOOTAGE,
    duration_seconds=8,
    prompt="Ancient underground tunnel.",
    provider="Stock Provider",
    source_url="https://example.com/stock-video.mp4",
    license_type="royalty_free",
    source_status=SceneSourceStatus.READY,
    status=VideoClipStatus.READY,
)

local_clip = VideoClip(
    scene_number=3,
    source_type=SceneSourceType.LOCAL_LIBRARY,
    duration_seconds=8,
    provider="Local Library",
    local_file="assets/videos/local/tunnel.mp4",
    source_status=SceneSourceStatus.READY,
    status=VideoClipStatus.READY,
)

image_clip = VideoClip(
    scene_number=4,
    source_type=SceneSourceType.IMAGE_TO_VIDEO,
    duration_seconds=8,
    provider="Image To Video",
    local_file="outputs/video/image_scene_004.mp4",
    source_status=SceneSourceStatus.READY,
    status=VideoClipStatus.READY,
)

disabled_ai_clip = VideoClip(
    scene_number=5,
    source_type=SceneSourceType.AI_GENERATE,
    duration_seconds=8,
    provider="Future AI Video Provider",
    source_status=SceneSourceStatus.DISABLED,
    status=VideoClipStatus.PENDING,
)

print("Manual:", manual_clip.source_type, manual_clip.local_file)
print("Stock:", stock_clip.source_type, stock_clip.source_url)
print("Local:", local_clip.source_type, local_clip.local_file)
print("Image:", image_clip.source_type, image_clip.local_file)
print("AI:", disabled_ai_clip.source_type, disabled_ai_clip.source_status)

try:
    VideoClip(
        scene_number=6,
        source_type=SceneSourceType.MANUAL_UPLOAD,
        duration_seconds=8,
        source_status=SceneSourceStatus.READY,
        status=VideoClipStatus.READY,
    )
except ValidationError:
    print("Ready clip without file successfully blocked.")
else:
    raise AssertionError("A ready clip without a file should not be allowed.")

assert manual_clip.status == VideoClipStatus.READY
assert stock_clip.license_type == "royalty_free"
assert disabled_ai_clip.source_status == SceneSourceStatus.DISABLED

print("Generic Video Clip tests completed successfully.")
