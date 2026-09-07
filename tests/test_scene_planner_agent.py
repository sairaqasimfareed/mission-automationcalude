from src.agents.scene_planner.agent import ScenePlannerAgent
from src.models.media_strategy import SceneSourceType
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


# --- External audit fix: genre-based default acquisition route ---
# Post-Script-Approval Production Plan Phase 6: "Apply route defaults
# by project/genre with per-clip override." No genre_id given -
# preserves the exact prior MANUAL_UPLOAD-uniform behavior rather than
# guessing a genre.
assert all(scene.source_type == SceneSourceType.MANUAL_UPLOAD for scene in scenes)
assert all(scene.stock_query is None for scene in scenes)

# genre.documentary's real default is STOCK_FOOTAGE (real-world
# footage genres) - Scene's own validator requires a non-empty
# stock_query whenever source_type is STOCK_FOOTAGE, so this also
# proves a real value is supplied, not just the enum flipped.
documentary_scenes = agent.plan(script, genre_id="genre.documentary")

assert all(
    scene.source_type == SceneSourceType.STOCK_FOOTAGE for scene in documentary_scenes
)
assert all(scene.stock_query == scene.visual_prompt for scene in documentary_scenes)

# genre.horror's real default is MANUAL_UPLOAD (staged/dramatized
# content) - an unknown genre_id falls back to genre.default, also
# MANUAL_UPLOAD.
horror_scenes = agent.plan(script, genre_id="genre.horror")
unknown_genre_scenes = agent.plan(script, genre_id="genre.not_a_real_genre")

assert all(
    scene.source_type == SceneSourceType.MANUAL_UPLOAD for scene in horror_scenes
)
assert all(
    scene.source_type == SceneSourceType.MANUAL_UPLOAD for scene in unknown_genre_scenes
)

print("Scene Planner Agent tests completed successfully.")
