from __future__ import annotations

from src.models.editing_directives import (
    CameraDirective,
    SceneEditingDirectives,
)
from src.models.genre_timeline_pipeline import (
    GenreTimelinePipelineStatus,
)
from src.models.media_strategy import (
    SceneSourceStatus,
    SceneSourceType,
)
from src.models.scene import (
    Scene,
    SceneStatus,
)
from src.models.video_clip import (
    VideoClip,
    VideoClipStatus,
)
from src.services.editing_directive_resolution_service import (
    EditingDirectiveResolutionService,
)
from src.services.effect_registry_service import (
    EffectRegistryService,
)
from src.services.genre_directive_generation_service import (
    GenreDirectiveGenerationService,
)
from src.services.genre_profile_registry_service import (
    GenreProfileRegistryService,
)
from src.services.genre_timeline_pipeline_service import (
    GenreTimelinePipelineService,
)


def build_scene(
    *,
    scene_number: int,
    duration_seconds: int,
) -> Scene:
    return Scene(
        scene_number=scene_number,
        title=f"Scene {scene_number}",
        narration=(f"Narration for scene {scene_number}."),
        visual_prompt=(f"Visual prompt for scene {scene_number}."),
        estimated_duration_seconds=(duration_seconds),
        status=SceneStatus.READY,
    )


def build_clip(
    *,
    scene_number: int,
    duration_seconds: int,
) -> VideoClip:
    return VideoClip(
        scene_number=scene_number,
        source_type=(SceneSourceType.MANUAL_UPLOAD),
        duration_seconds=duration_seconds,
        prompt=f"Scene {scene_number}",
        provider="Manual Upload",
        local_file=("assets/videos/manual/" f"scene_{scene_number:03}.mp4"),
        source_status=SceneSourceStatus.READY,
        status=VideoClipStatus.READY,
    )


genre_registry = GenreProfileRegistryService.with_default_profiles()

effect_registry = EffectRegistryService.with_default_presets()

genre_directive_service = GenreDirectiveGenerationService(
    genre_registry=genre_registry,
)

directive_resolution_service = EditingDirectiveResolutionService(
    effect_registry=effect_registry,
)

pipeline = GenreTimelinePipelineService(
    genre_directive_service=(genre_directive_service),
    directive_resolution_service=(directive_resolution_service),
)


scenes = [
    build_scene(
        scene_number=2,
        duration_seconds=10,
    ),
    build_scene(
        scene_number=1,
        duration_seconds=8,
    ),
]

clips = [
    build_clip(
        scene_number=1,
        duration_seconds=8,
    ),
    build_clip(
        scene_number=2,
        duration_seconds=10,
    ),
]


result = pipeline.build(
    scenes=scenes,
    clips=clips,
    genre_id="genre.horror",
)

print("Status:", result.status)
print("Scenes:", result.scene_count)
print(
    "Render ready:",
    result.is_render_ready,
)
print(
    "Duration:",
    result.timeline.total_duration_seconds,
)

assert result.is_successful is True
assert result.is_render_ready is True

assert result.status == GenreTimelinePipelineStatus.COMPLETED

assert result.scene_count == 2
assert result.fallback_count == 0

assert len(result.directives) == 2
assert len(result.blueprints) == 2
assert len(result.timeline.items) == 2

assert result.timeline.total_duration_seconds == 18.0

assert result.validation.all_enabled_items_render_ready is True

assert result.validation.render_ready_item_count == 2

assert all(item.editing_blueprint is not None for item in result.timeline.items)

assert [directive.scene_number for directive in result.directives] == [
    1,
    2,
]

assert [item.scene_number for item in result.timeline.items] == [
    1,
    2,
]


override_result = pipeline.build(
    scenes=scenes,
    clips=clips,
    genre_id="genre.horror",
    overrides_by_scene={
        2: SceneEditingDirectives(
            scene_number=2,
            camera=CameraDirective(
                preset_id=("camera.unknown_motion"),
            ),
        )
    },
)

assert override_result.is_successful is True
assert override_result.is_render_ready is True

assert override_result.status == GenreTimelinePipelineStatus.COMPLETED_WITH_WARNINGS

assert override_result.fallback_count == 1
assert override_result.warnings

scene_2_item = next(
    item for item in override_result.timeline.items if item.scene_number == 2
)

assert scene_2_item.editing_blueprint is not None

assert scene_2_item.editing_blueprint.camera.preset.resolved_preset_id == "camera.none"


unknown_genre_result = pipeline.build(
    scenes=scenes,
    clips=clips,
    genre_id="genre.not_registered",
)

assert unknown_genre_result.is_successful is True
assert unknown_genre_result.is_render_ready is True

assert (
    unknown_genre_result.status == GenreTimelinePipelineStatus.COMPLETED_WITH_WARNINGS
)

assert unknown_genre_result.warnings

assert all(
    (directive.metadata["genre_fallback_used"] is True)
    for directive in (unknown_genre_result.directives)
)


try:
    pipeline.build(
        scenes=scenes,
        clips=[
            clips[0],
        ],
        genre_id="genre.horror",
    )
except ValueError:
    print("Missing clip successfully blocked.")
else:
    raise AssertionError("Every scene must have a video clip.")


try:
    pipeline.build(
        scenes=scenes,
        clips=[
            build_clip(
                scene_number=1,
                duration_seconds=7,
            ),
            clips[1],
        ],
        genre_id="genre.horror",
    )
except ValueError:
    print("Duration mismatch successfully blocked.")
else:
    raise AssertionError("Scene and clip durations must match.")


try:
    pipeline.build(
        scenes=[
            scenes[0],
            scenes[0],
        ],
        clips=clips,
        genre_id="genre.horror",
    )
except ValueError:
    print("Duplicate scenes successfully blocked.")
else:
    raise AssertionError("Duplicate scenes should fail.")


try:
    pipeline.build(
        scenes=scenes,
        clips=[
            clips[0],
            clips[0],
        ],
        genre_id="genre.horror",
    )
except ValueError:
    print("Duplicate clips successfully blocked.")
else:
    raise AssertionError("Duplicate clip scenes should fail.")


try:
    pipeline.build(
        scenes=scenes,
        clips=clips,
        genre_id="",
    )
except ValueError:
    print("Empty genre successfully blocked.")
else:
    raise AssertionError("Empty genre ID should fail.")


print("Genre Timeline Pipeline Service tests " "completed successfully.")
