from src.models.media_strategy import (
    SceneSourceStatus,
    SceneSourceType,
)
from src.models.render_result import RenderStatus
from src.models.video_clip import (
    VideoClip,
    VideoClipStatus,
)
from src.models.video_timeline import VideoTimeline
from src.services.render_service import RenderService


timeline = VideoTimeline(
    clips=[
        VideoClip(
            scene_number=1,
            source_type=SceneSourceType.MANUAL_UPLOAD,
            duration_seconds=8,
            prompt="Scene 1",
            provider="Manual Upload",
            local_file=(
                "assets/videos/manual/"
                "scene_001.mp4"
            ),
            source_status=SceneSourceStatus.READY,
            status=VideoClipStatus.READY,
        ),
        VideoClip(
            scene_number=2,
            source_type=SceneSourceType.STOCK_FOOTAGE,
            duration_seconds=8,
            prompt="Scene 2",
            provider="Pexels",
            source_url=(
                "https://example.com/"
                "scene_002.mp4"
            ),
            source_status=SceneSourceStatus.READY,
            status=VideoClipStatus.READY,
        ),
        VideoClip(
            scene_number=3,
            source_type=SceneSourceType.LOCAL_LIBRARY,
            duration_seconds=10,
            prompt="Scene 3",
            provider="Local Library",
            local_file=(
                "assets/videos/local/"
                "scene_003.mp4"
            ),
            source_status=SceneSourceStatus.READY,
            status=VideoClipStatus.READY,
        ),
    ]
)

service = RenderService()

result = service.render(timeline)

print("Success:", result.success)
print("Engine:", result.render_engine)
print("Status:", result.status)
print("Duration:", result.duration_seconds)
print("Output:", result.output_file)

assert result.success is True
assert result.status == RenderStatus.COMPLETED
assert result.duration_seconds == 26

print(
    "Render Service tests completed successfully."
)