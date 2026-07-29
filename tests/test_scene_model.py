from src.models.scene import Scene, SceneStatus

scene = Scene(
    scene_number=1,
    title="Opening Hook",
    narration="Beneath ordinary streets, entire cities once existed.",
    visual_prompt=(
        "Ultra realistic underground city, cinematic lighting, " "8K, volumetric fog"
    ),
    estimated_duration_seconds=8,
    camera_direction="Slow cinematic push in",
    sound_design="Deep ambient cinematic drone",
    status=SceneStatus.READY,
)

print("Scene Number:", scene.scene_number)
print("Title:", scene.title)
print("Status:", scene.status)
print("Duration:", scene.estimated_duration_seconds)

assert scene.status == SceneStatus.READY

print("Scene Model tests completed successfully.")
