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
            prompt="Scene 1",
            duration_seconds=8,
            provider="Google Veo",
            model_name="veo-3",
            status=VideoClipStatus.GENERATED,
        ),
        VideoClip(
            scene_number=2,
            prompt="Scene 2",
            duration_seconds=8,
            provider="Google Veo",
            model_name="veo-3",
            status=VideoClipStatus.GENERATED,
        ),
        VideoClip(
            scene_number=3,
            prompt="Scene 3",
            duration_seconds=10,
            provider="Google Veo",
            model_name="veo-3",
            status=VideoClipStatus.GENERATED,
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

print("Render Service tests completed successfully.")
