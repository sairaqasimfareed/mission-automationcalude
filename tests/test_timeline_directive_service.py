from __future__ import annotations

from src.models.editing_directives import (
    CameraDirective,
    SceneEditingDirectives,
    TransitionDirective,
    VisualEffectDirective,
)
from src.models.media_strategy import (
    SceneSourceStatus,
    SceneSourceType,
)
from src.models.resolved_editing_blueprint import (
    BlueprintResolutionStatus,
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
from src.services.timeline_builder_service import (
    TimelineBuilderService,
)
from src.services.timeline_directive_service import (
    TimelineDirectiveService,
)


def build_clip(
    *,
    scene_number: int,
    duration_seconds: int,
) -> VideoClip:
    return VideoClip(
        scene_number=scene_number,
        source_type=(
            SceneSourceType.MANUAL_UPLOAD
        ),
        duration_seconds=duration_seconds,
        prompt=f"Scene {scene_number}",
        provider="Manual Upload",
        local_file=(
            "assets/videos/manual/"
            f"scene_{scene_number:03}.mp4"
        ),
        source_status=SceneSourceStatus.READY,
        status=VideoClipStatus.READY,
    )


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

timeline = TimelineBuilderService().build(
    clips
)

registry = (
    EffectRegistryService
    .with_default_presets()
)

resolution_service = (
    EditingDirectiveResolutionService(
        effect_registry=registry,
    )
)

timeline_directive_service = (
    TimelineDirectiveService()
)


scene_1_directives = SceneEditingDirectives(
    scene_number=1,
    genre_preset_id="genre.horror",
    camera=CameraDirective(
        preset_id="camera.slow_zoom_in",
        end_offset_seconds=8.0,
    ),
    transition_in=TransitionDirective(
        preset_id="transition.fade_black",
        duration_seconds=0.8,
    ),
    transition_out=TransitionDirective(
        preset_id="transition.cross_dissolve",
        duration_seconds=0.6,
    ),
    visual_effects=[
        VisualEffectDirective(
            preset_id=(
                "visual.horror_dark_grade"
            ),
        )
    ],
)

scene_1_blueprint = (
    resolution_service.resolve(
        scene_1_directives,
        scene_duration_seconds=8.0,
    )
)

attached_item = (
    timeline_directive_service
    .attach_blueprint(
        timeline,
        blueprint=scene_1_blueprint,
    )
)

print(
    "Attached scene:",
    attached_item.scene_number,
)
print(
    "Transition in:",
    attached_item.transition_in,
)

assert attached_item.scene_number == 1
assert attached_item.has_editing_blueprint is True
assert attached_item.is_render_ready is True

assert (
    attached_item.transition_in
    == "transition.fade_black"
)

assert (
    attached_item.transition_out
    == "transition.cross_dissolve"
)

assert (
    attached_item.metadata[
        "editing_blueprint_attached"
    ]
    is True
)

assert (
    timeline_directive_service
    .scenes_without_blueprints(timeline)
    == [2]
)


scene_2_directives = SceneEditingDirectives(
    scene_number=2,
    camera=CameraDirective(
        preset_id="camera.unknown_motion",
    ),
)

scene_2_blueprint = (
    resolution_service.resolve(
        scene_2_directives,
        scene_duration_seconds=10.0,
    )
)

assert (
    scene_2_blueprint.status
    == BlueprintResolutionStatus
    .RESOLVED_WITH_FALLBACKS
)

attached_items = (
    timeline_directive_service.attach_many(
        timeline,
        blueprints=[
            scene_2_blueprint,
        ],
    )
)

assert len(attached_items) == 1

assert (
    timeline_directive_service
    .scenes_without_blueprints(timeline)
    == []
)

render_ready_items = (
    timeline_directive_service
    .render_ready_items(timeline)
)

assert len(render_ready_items) == 2

assert (
    timeline.items[1]
    .editing_blueprint
    is not None
)

assert (
    timeline.items[1]
    .editing_blueprint
    .fallback_count
    == 1
)


applied_item = (
    timeline_directive_service.mark_applied(
        timeline,
        scene_number=1,
    )
)

assert (
    applied_item.editing_blueprint
    is not None
)

assert (
    applied_item.editing_blueprint.status
    == BlueprintResolutionStatus.APPLIED
)

assert (
    applied_item.metadata[
        "editing_blueprint_status"
    ]
    == "applied"
)


detached_blueprint = (
    timeline_directive_service
    .detach_blueprint(
        timeline,
        scene_number=2,
    )
)

assert detached_blueprint.scene_number == 2
assert (
    timeline.items[1].editing_blueprint
    is None
)
assert timeline.items[1].transition_in is None
assert timeline.items[1].transition_out is None


try:
    timeline_directive_service.attach_blueprint(
        timeline,
        blueprint=scene_1_blueprint,
    )
except ValueError:
    print(
        "Duplicate blueprint attachment "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "Existing blueprint should require replace=True."
    )


wrong_scene_directives = (
    SceneEditingDirectives(
        scene_number=99,
    )
)

wrong_scene_blueprint = (
    resolution_service.resolve(
        wrong_scene_directives,
        scene_duration_seconds=8.0,
    )
)

try:
    timeline_directive_service.attach_blueprint(
        timeline,
        blueprint=wrong_scene_blueprint,
    )
except KeyError:
    print(
        "Unknown timeline scene blueprint "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "Unknown scene blueprint should fail."
    )


try:
    timeline_directive_service.attach_many(
        timeline,
        blueprints=[
            scene_1_blueprint,
        ],
        replace=True,
        require_all_timeline_scenes=True,
    )
except ValueError:
    print(
        "Incomplete blueprint collection "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "All enabled scenes should require blueprints."
    )


print(
    "Timeline Directive Service tests "
    "completed successfully."
)