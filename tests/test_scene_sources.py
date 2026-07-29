from pydantic import ValidationError

from src.models.media_strategy import (
    SceneSourceStatus,
    SceneSourceType,
)
from src.models.scene import Scene, SceneStatus

manual_scene = Scene(
    scene_number=1,
    title="Manual Veo Clip",
    narration="A hidden city appears beneath the streets.",
    visual_prompt="Cinematic underground city.",
    estimated_duration_seconds=8,
    source_type=SceneSourceType.MANUAL_UPLOAD,
    source_status=SceneSourceStatus.WAITING_FOR_UPLOAD,
    status=SceneStatus.READY,
)

print("Manual source:", manual_scene.source_type)
print("Manual status:", manual_scene.source_status)


stock_scene = Scene(
    scene_number=2,
    title="Historical Footage",
    narration="Ancient tunnels protected entire communities.",
    visual_prompt="Historical underground tunnel footage.",
    estimated_duration_seconds=8,
    source_type=SceneSourceType.STOCK_FOOTAGE,
    source_status=SceneSourceStatus.SEARCHING,
    stock_query="ancient underground tunnels",
    fallback_sources=[
        SceneSourceType.LOCAL_LIBRARY,
        SceneSourceType.MANUAL_UPLOAD,
    ],
    status=SceneStatus.READY,
)

print("Stock source:", stock_scene.source_type)
print("Stock query:", stock_scene.stock_query)


local_scene = Scene(
    scene_number=3,
    title="Local Asset",
    narration="The camera moves through a stone passage.",
    visual_prompt="Dark stone corridor.",
    estimated_duration_seconds=8,
    source_type=SceneSourceType.LOCAL_LIBRARY,
    source_status=SceneSourceStatus.SEARCHING,
    local_library_query="dark stone corridor",
    status=SceneStatus.READY,
)

print("Local source:", local_scene.source_type)


image_scene = Scene(
    scene_number=4,
    title="Image Motion",
    narration="An ancient map reveals the hidden city.",
    visual_prompt="Ancient map with cinematic movement.",
    estimated_duration_seconds=8,
    source_type=SceneSourceType.IMAGE_TO_VIDEO,
    source_status=SceneSourceStatus.PROCESSING,
    image_prompt="Ancient underground city map",
    status=SceneStatus.READY,
)

print("Image source:", image_scene.source_type)


disabled_ai_scene = Scene(
    scene_number=5,
    title="Future AI Generation",
    narration="Reserved for future video API integration.",
    visual_prompt="Future AI-generated visual.",
    estimated_duration_seconds=8,
    source_type=SceneSourceType.AI_GENERATE,
    source_status=SceneSourceStatus.DISABLED,
    status=SceneStatus.PENDING,
)

print("AI source:", disabled_ai_scene.source_type)
print("AI status:", disabled_ai_scene.source_status)


try:
    Scene(
        scene_number=6,
        title="Invalid AI Scene",
        narration="This state must be blocked.",
        visual_prompt="Invalid AI generation request.",
        estimated_duration_seconds=8,
        source_type=SceneSourceType.AI_GENERATE,
        source_status=SceneSourceStatus.PENDING,
    )
except ValidationError:
    print("Invalid AI source state successfully blocked.")
else:
    raise AssertionError("AI_GENERATE should remain disabled.")


assert manual_scene.source_status == SceneSourceStatus.WAITING_FOR_UPLOAD
assert stock_scene.stock_query == "ancient underground tunnels"
assert local_scene.local_library_query == "dark stone corridor"
assert image_scene.image_prompt == "Ancient underground city map"
assert disabled_ai_scene.source_status == SceneSourceStatus.DISABLED

print("Scene Source tests completed successfully.")
