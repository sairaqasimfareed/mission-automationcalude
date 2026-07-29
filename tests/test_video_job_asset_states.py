from pydantic import ValidationError

from src.models.asset_state import (
    AssetWorkflowStatus,
    SceneAssetState,
)
from src.models.research import ResearchResult, ResearchStatus
from src.models.scene import Scene, SceneStatus
from src.models.script import (
    Script,
    ScriptReviewStatus,
    ScriptStatus,
)
from src.models.video_job import VideoJob

research = ResearchResult(
    topic="Hidden Underground Cities",
    research_summary="Approved research summary.",
    key_facts=[
        "Underground cities existed.",
        "They were used for protection.",
    ],
    prompt_version="research_prompt_v1.0.0",
    status=ResearchStatus.APPROVED,
)

script = Script(
    title=research.topic,
    content="A hidden city existed beneath ordinary streets.",
    prompt_version="script_prompt_v1.0.0",
    word_count=8,
    estimated_duration_seconds=4,
    status=ScriptStatus.APPROVED,
    claude_review_status=ScriptReviewStatus.APPROVED,
)

scene = Scene(
    scene_number=1,
    title="Opening",
    narration="A hidden city existed beneath ordinary streets.",
    visual_prompt="Cinematic underground city.",
    estimated_duration_seconds=8,
    status=SceneStatus.READY,
)

state = SceneAssetState(
    scene_id=str(scene.id),
    scene_number=1,
    status=AssetWorkflowStatus.SEARCHING_LOCAL,
    local_search_query="cinematic underground city",
)

job = VideoJob(
    project_name="Mission Automation",
    channel_name="Beyond the Ninth",
    niche="Mystery",
    topic=research.topic,
    research=research,
    script=script,
    scenes=[scene],
    scene_asset_states=[state],
)

print("Scenes:", len(job.scenes))
print("Asset states:", len(job.scene_asset_states))
print("State status:", job.scene_asset_states[0].status)

assert len(job.scenes) == 1
assert len(job.scene_asset_states) == 1
assert job.scene_asset_states[0].scene_number == job.scenes[0].scene_number


try:
    invalid_state = SceneAssetState(
        scene_id="missing-scene",
        scene_number=99,
        status=AssetWorkflowStatus.PENDING,
    )

    VideoJob(
        project_name="Mission Automation",
        channel_name="Beyond the Ninth",
        niche="Mystery",
        topic=research.topic,
        research=research,
        script=script,
        scenes=[scene],
        scene_asset_states=[invalid_state],
    )
except ValidationError:
    print("Invalid scene asset state successfully blocked.")
else:
    raise AssertionError("A state for a missing scene should be blocked.")


print("VideoJob Asset State tests completed successfully.")
