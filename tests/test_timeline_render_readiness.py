from __future__ import annotations

from src.models.editing_directives import (
    CameraDirective,
    SceneEditingDirectives,
)
from src.models.media_strategy import (
    SceneSourceStatus,
    SceneSourceType,
)
from src.models.timeline_validation import (
    TimelineValidationCode,
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
from src.services.timeline_validation_service import (
    TimelineValidationService,
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

validator = TimelineValidationService()

# Backward-compatible validation does not require blueprints.
legacy_result = validator.validate(
    timeline
)

assert legacy_result.is_valid is True
assert legacy_result.blueprint_count == 0
assert legacy_result.render_ready_item_count == 0
assert (
    legacy_result
    .all_enabled_items_render_ready
    is False
)


# Strict render validation requires blueprints.
missing_blueprint_result = validator.validate(
    timeline,
    require_editing_blueprints=True,
)

assert missing_blueprint_result.is_valid is False

assert len(
    [
        issue
        for issue in missing_blueprint_result.errors
        if (
            issue.code
            == TimelineValidationCode
            .MISSING_EDITING_BLUEPRINT
        )
    ]
) == 2


registry = (
    EffectRegistryService
    .with_default_presets()
)

resolution_service = (
    EditingDirectiveResolutionService(
        effect_registry=registry,
    )
)

attachment_service = (
    TimelineDirectiveService()
)


scene_1_blueprint = resolution_service.resolve(
    SceneEditingDirectives(
        scene_number=1,
        camera=CameraDirective(
            preset_id="camera.slow_zoom_in",
            end_offset_seconds=8.0,
        ),
    ),
    scene_duration_seconds=8.0,
)

attachment_service.attach_blueprint(
    timeline,
    blueprint=scene_1_blueprint,
)


partially_ready_result = validator.validate(
    timeline,
    require_editing_blueprints=True,
)

assert partially_ready_result.is_valid is False
assert partially_ready_result.blueprint_count == 1

assert (
    partially_ready_result
    .render_ready_item_count
    == 1
)

assert (
    partially_ready_result
    .all_enabled_items_render_ready
    is False
)


# Unknown camera ID resolves safely to camera.none.
scene_2_blueprint = resolution_service.resolve(
    SceneEditingDirectives(
        scene_number=2,
        camera=CameraDirective(
            preset_id="camera.unknown_motion",
        ),
    ),
    scene_duration_seconds=10.0,
)

attachment_service.attach_blueprint(
    timeline,
    blueprint=scene_2_blueprint,
)


render_ready_result = validator.validate(
    timeline,
    require_editing_blueprints=True,
)

print(
    "Render-ready:",
    render_ready_result.is_valid,
)

print(
    "Ready items:",
    render_ready_result.render_ready_item_count,
)

print(
    "Fallbacks:",
    render_ready_result.blueprint_fallback_count,
)

assert render_ready_result.is_valid is True
assert render_ready_result.blueprint_count == 2

assert (
    render_ready_result
    .render_ready_item_count
    == 2
)

assert (
    render_ready_result
    .all_enabled_items_render_ready
    is True
)

assert (
    render_ready_result
    .blueprint_fallback_count
    == 1
)

assert any(
    issue.code
    == TimelineValidationCode
    .EDITING_BLUEPRINT_FALLBACK_USED
    for issue in render_ready_result.warnings
)


no_fallback_warning_result = validator.validate(
    timeline,
    require_editing_blueprints=True,
    warn_on_blueprint_fallbacks=False,
)

assert no_fallback_warning_result.is_valid is True

assert not any(
    issue.code
    == TimelineValidationCode
    .EDITING_BLUEPRINT_FALLBACK_USED
    for issue in (
        no_fallback_warning_result.warnings
    )
)


print(
    "Timeline Render Readiness tests "
    "completed successfully."
)