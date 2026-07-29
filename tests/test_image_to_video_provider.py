from src.models.media_strategy import SceneSourceType
from src.models.scene import Scene, SceneStatus
from src.models.video_clip import VideoClipStatus
from src.providers.image_to_video_provider import (
    ImageToVideoProvider,
)

scene = Scene(
    scene_number=1,
    title="Opening",
    narration="Opening narration",
    visual_prompt="Ancient underground city",
    image_prompt=(
        "Ultra realistic ancient underground city, "
        "cinematic lighting, volumetric fog, "
        "camera dolly shot"
    ),
    estimated_duration_seconds=8,
    source_type=SceneSourceType.IMAGE_TO_VIDEO,
    status=SceneStatus.READY,
)

provider = ImageToVideoProvider()
clip = provider.acquire(scene)

print("Provider:", clip.provider)
print("Prompt:", clip.prompt)
print("Output:", clip.local_file)

assert clip.provider == "Image-to-Video Provider"
assert clip.status == VideoClipStatus.READY
assert clip.prompt == scene.image_prompt

print("Image-to-Video Provider tests completed successfully.")
