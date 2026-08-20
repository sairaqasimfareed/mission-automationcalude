from __future__ import annotations

from src.models.editing_directives import (
    AnimationDirective,
    CameraDirective,
    MusicDirective,
    SceneEditingDirectives,
    SoundEffectDirective,
    SubtitleDirective,
    TransitionDirective,
    VisualEffectDirective,
)
from src.models.resolved_editing_blueprint import (
    BlueprintResolutionStatus,
)
from src.services.editing_directive_resolution_service import (
    EditingDirectiveResolutionService,
)
from src.services.effect_registry_service import (
    EffectRegistryService,
)

registry = EffectRegistryService.with_default_presets()

service = EditingDirectiveResolutionService(
    effect_registry=registry,
)


directives = SceneEditingDirectives(
    scene_number=1,
    genre_preset_id="genre.horror",
    camera=CameraDirective(
        preset_id="camera.slow_zoom_in",
        end_offset_seconds=8.0,
        zoom_start=1.0,
        zoom_end=1.08,
    ),
    transition_in=TransitionDirective(
        preset_id="transition.fade_black",
        duration_seconds=0.8,
    ),
    transition_out=TransitionDirective(
        preset_id=("transition.cross_dissolve"),
        duration_seconds=0.6,
    ),
    visual_effects=[
        VisualEffectDirective(
            preset_id=("visual.horror_dark_grade"),
        ),
        VisualEffectDirective(
            preset_id="visual.vignette_soft",
        ),
    ],
    animations=[
        AnimationDirective(
            preset_id=("animation.slow_parallax"),
            duration_seconds=8.0,
        ),
    ],
    music=MusicDirective(
        preset_id="music.horror_low_drone",
        volume_percent=25.0,
    ),
    sound_effects=[
        SoundEffectDirective(
            preset_id="sfx.door_creak",
            start_offset_seconds=4.0,
        ),
    ],
    subtitles=SubtitleDirective(
        preset_id="subtitle.cinematic",
        animation_preset_id=("animation.subtitle_fade"),
    ),
)

blueprint = service.resolve(
    directives,
    scene_duration_seconds=8.0,
)

print("Status:", blueprint.status)
print(
    "Camera:",
    blueprint.camera.preset.resolved_preset_id,
)
print(
    "Visual effects:",
    len(blueprint.visual_effects),
)

assert blueprint.is_resolved is True
assert blueprint.status == BlueprintResolutionStatus.RESOLVED
assert blueprint.uses_fallbacks is False
assert blueprint.fallback_count == 0

assert blueprint.genre_preset.resolved_preset_id == "genre.horror"

assert blueprint.camera.preset.resolved_preset_id == "camera.slow_zoom_in"

assert blueprint.camera.preset.implementation["motion"] == "zoom"

assert blueprint.transition_in.preset.resolved_preset_id == "transition.fade_black"

assert len(blueprint.visual_effects) == 2
assert len(blueprint.animations) == 1
assert len(blueprint.sound_effects) == 1

assert blueprint.music.preset.resolved_preset_id == "music.horror_low_drone"

assert blueprint.subtitles.animation_preset is not None

assert (
    blueprint.subtitles.animation_preset.resolved_preset_id == "animation.subtitle_fade"
)


fallback_directives = SceneEditingDirectives(
    scene_number=2,
    camera=CameraDirective(
        preset_id="camera.unknown_motion",
    ),
    visual_effects=[
        VisualEffectDirective(
            preset_id="visual.unknown_grade",
        ),
    ],
    sound_effects=[
        SoundEffectDirective(
            preset_id="sfx.unknown_sound",
        ),
    ],
)

fallback_blueprint = service.resolve(
    fallback_directives,
    scene_duration_seconds=8.0,
)

print(
    "Fallback status:",
    fallback_blueprint.status,
)

assert fallback_blueprint.is_resolved is True

assert fallback_blueprint.status == BlueprintResolutionStatus.RESOLVED_WITH_FALLBACKS

assert fallback_blueprint.uses_fallbacks is True
assert fallback_blueprint.fallback_count == 3

assert fallback_blueprint.camera.preset.resolved_preset_id == "camera.none"

assert fallback_blueprint.visual_effects[0].preset.resolved_preset_id == "visual.none"

assert fallback_blueprint.sound_effects[0].preset.resolved_preset_id == "sfx.none"

assert len(fallback_blueprint.warnings) == 3


invalid_directives = SceneEditingDirectives(
    scene_number=3,
    camera=CameraDirective(
        preset_id="camera.slow_zoom_in",
        end_offset_seconds=12.0,
    ),
)

try:
    service.resolve(
        invalid_directives,
        scene_duration_seconds=8.0,
    )
except ValueError:
    print("Invalid directive blueprint " "successfully blocked.")
else:
    raise AssertionError("Invalid directive timing should fail.")


print("Editing Directive Resolution Service " "tests completed successfully.")
