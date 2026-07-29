from src.agents.scene_planner.agent import ScenePlannerAgent
from src.models.scene import SceneStatus
from src.models.script import Script, ScriptStatus


script = Script(
    title="Top 10 Hidden Underground Cities",
    content=(
        "Beneath ordinary streets, entire cities once existed in silence. "
        "These hidden spaces protected communities from invasion. "
        "Some included homes, tunnels, and food storage."
    ),
    prompt_version="script_prompt_v1.0.0",
    word_count=22,
    estimated_duration_seconds=10,
    status=ScriptStatus.APPROVED,
)

agent = ScenePlannerAgent()
scenes = agent.plan(script)

print("Total scenes:", len(scenes))

for scene in scenes:
    print(
        scene.scene_number,
        scene.title,
        scene.status,
        scene.estimated_duration_seconds,
    )

assert len(scenes) == 3
assert all(scene.status == SceneStatus.READY for scene in scenes)

print("Scene Planner Agent tests completed successfully.")