from src.agents.veo_generator.agent import VeoGeneratorAgent
from src.models.scene import Scene, SceneStatus
from src.models.video_clip import VideoClipStatus


scene = Scene(
    scene_number=1,
    title="Opening Hook",
    narration="Beneath ordinary streets, entire cities once existed.",
    visual_prompt=(
        "Ultra realistic underground city, cinematic lighting, "
        "8K, volumetric fog."
    ),
    estimated_duration_seconds=8,
    camera_direction="Slow cinematic push in",
    sound_design="Deep cinematic ambience",
    status=SceneStatus.READY,
)

agent = VeoGeneratorAgent()

clip = agent.generate(scene)

print("Scene:", clip.scene_number)
print("Status:", clip.status)
print("Provider:", clip.provider)
print("Model:", clip.model_name)
print("Output:", clip.output_file)
print("Credits:", clip.cost_credits)

assert clip.status == VideoClipStatus.GENERATED
assert clip.scene_number == 1

print("Veo Generator tests completed successfully.")