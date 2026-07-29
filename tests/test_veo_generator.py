from src.agents.veo_generator.agent import VeoGeneratorAgent
from src.models.scene import Scene, SceneStatus
from src.models.video_clip import VideoClipStatus

scene = Scene(
    scene_number=1,
    title="Opening Scene",
    purpose="Introduce the topic",
    narration="This is the opening narration.",
    visual_prompt="A cinematic aerial shot of an ancient city.",
    camera_direction="Slow aerial push-in",
    sound_design="Soft cinematic ambience",
    estimated_duration_seconds=8,
    status=SceneStatus.READY,
)

agent = VeoGeneratorAgent()

clip = agent.generate(scene)

print("Scene:", clip.scene_number)
print("Status:", clip.status)
print("Provider:", clip.provider)
print("Model:", clip.metadata["model_name"])
print("Output:", clip.local_file)
print(
    "Generation time:",
    clip.acquisition_time_seconds,
)
print(
    "Estimated credits:",
    clip.metadata["estimated_cost_credits"],
)

assert clip.scene_number == 1
assert clip.status == VideoClipStatus.READY
assert clip.provider == "Google Veo"
assert clip.metadata["model_name"] == "veo-3"
assert clip.local_file == "outputs/video/scene_001.mp4"
assert clip.acquisition_time_seconds >= 0.0
assert clip.metadata["estimated_cost_credits"] == 120
assert clip.metadata["dry_run"] is True

print("Veo Generator tests completed successfully.")
