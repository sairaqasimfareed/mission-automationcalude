from pathlib import Path

from src.models.media_strategy import (
    SceneSourceStatus,
    SceneSourceType,
)
from src.models.scene import Scene, SceneStatus
from src.models.video_clip import VideoClipStatus
from src.providers.manual_upload_provider import (
    ManualUploadProvider,
)

Path("assets/videos/manual").mkdir(
    parents=True,
    exist_ok=True,
)

dummy_file = (
    Path("assets/videos/manual")
    / "scene_001.mp4"
)

dummy_file.write_text(
    "dummy video",
    encoding="utf-8",
)

scene = Scene(
    scene_number=1,
    title="Opening",
    narration="Opening narration",
    visual_prompt="Ancient underground city",
    estimated_duration_seconds=8,
    source_type=SceneSourceType.MANUAL_UPLOAD,
    source_status=SceneSourceStatus.WAITING_FOR_UPLOAD,
    manual_file_path=str(dummy_file),
    status=SceneStatus.READY,
)

provider = ManualUploadProvider()

clip = provider.acquire(scene)

print("Provider :", clip.provider)
print("File     :", clip.local_file)
print("Status   :", clip.status)

assert clip.status == VideoClipStatus.READY
assert Path(clip.local_file).exists()

print(
    "Manual Upload Provider tests completed successfully."
)