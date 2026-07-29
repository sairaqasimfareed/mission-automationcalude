from src.models.video_clip import (
    VideoClip,
    VideoClipStatus,
)

clip = VideoClip(
    scene_number=1,
    prompt=(
        "Ultra realistic underground city, cinematic lighting, "
        "8K, volumetric fog."
    ),
    duration_seconds=8,
    provider="Google Veo",
    model_name="veo-3",
    status=VideoClipStatus.GENERATED,
    output_file="scene_001.mp4",
    generation_time_seconds=14.6,
    cost_credits=120,
)

print("Scene:", clip.scene_number)
print("Provider:", clip.provider)
print("Model:", clip.model_name)
print("Status:", clip.status)
print("Output:", clip.output_file)
print("Credits:", clip.cost_credits)

assert clip.status == VideoClipStatus.GENERATED
assert clip.duration_seconds == 8

print("Video Clip model tests completed successfully.")