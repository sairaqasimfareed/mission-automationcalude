from __future__ import annotations

from src.models.editing_directives import (
    AnimationDirective,
    CameraDirective,
    DirectiveTimingMode,
    EditingDirectiveStatus,
    MusicDirective,
    SceneEditingDirectives,
    SoundEffectDirective,
    TransitionDirective,
    VisualEffectDirective,
)
from src.services.editing_directive_validation_service import (
    EditingDirectiveValidationService,
)
from src.services.effect_registry_service import (
    EffectRegistryService,
)


registry = (
    EffectRegistryService
    .with_default_presets()
)

service = EditingDirectiveValidationService(
    effect_registry=registry,
    maximum_active_effects=6,
)


valid_directives = SceneEditingDirectives(
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
        ),
        VisualEffectDirective(
            preset_id="visual.vignette_soft",
        ),
    ],
    animations=[
        AnimationDirective(
            preset_id=(
                "animation.slow_parallax"
            ),
            duration_seconds=8.0,
        ),
    ],
    music=MusicDirective(
        preset_id="music.horror_low_drone",
        fade_in_seconds=0.5,
        fade_out_seconds=0.5,
    ),
    sound_effects=[
        SoundEffectDirective(
            preset_id="sfx.door_creak",
            start_offset_seconds=4.0,
        ),
    ],
)

valid_result = service.validate(
    valid_directives,
    scene_duration_seconds=8.0,
)

print("Valid:", valid_result.is_valid)
print(
    "Exact matches:",
    valid_result.exact_match_count,
)
print(
    "Fallbacks:",
    valid_result.fallback_count,
)

assert valid_result.is_valid is True
assert valid_result.is_render_ready is True
assert valid_result.unresolved_count == 0
assert valid_result.fallback_count == 0
assert valid_result.exact_match_count > 0
assert valid_result.errors == []


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

fallback_result = service.validate(
    fallback_directives,
    scene_duration_seconds=8.0,
)

print(
    "Fallback count:",
    fallback_result.fallback_count,
)

assert fallback_result.is_valid is True
assert fallback_result.is_render_ready is True
assert fallback_result.fallback_count == 3
assert fallback_result.unresolved_count == 0
assert len(fallback_result.warnings) == 3


timing_directives = SceneEditingDirectives(
    scene_number=3,
    camera=CameraDirective(
        preset_id="camera.slow_zoom_in",
        end_offset_seconds=12.0,
    ),
    animations=[
        AnimationDirective(
            preset_id=(
                "animation.slow_parallax"
            ),
            start_offset_seconds=7.0,
            duration_seconds=4.0,
        ),
    ],
    sound_effects=[
        SoundEffectDirective(
            preset_id="sfx.door_creak",
            timing_mode=(
                DirectiveTimingMode
                .ABSOLUTE_SECONDS
            ),
            start_offset_seconds=10.0,
        ),
    ],
)

timing_result = service.validate(
    timing_directives,
    scene_duration_seconds=8.0,
)

assert timing_result.is_valid is False
assert timing_result.is_render_ready is False
assert len(timing_result.errors) == 3


long_transition_directives = (
    SceneEditingDirectives(
        scene_number=4,
        transition_in=TransitionDirective(
            preset_id=(
                "transition.fade_black"
            ),
            duration_seconds=5.0,
        ),
        transition_out=TransitionDirective(
            preset_id=(
                "transition.cross_dissolve"
            ),
            duration_seconds=5.0,
        ),
    )
)

transition_result = service.validate(
    long_transition_directives,
    scene_duration_seconds=8.0,
)

assert transition_result.is_valid is False
assert len(transition_result.errors) == 1


updated_directives = SceneEditingDirectives(
    scene_number=5,
    camera=CameraDirective(
        preset_id="camera.unknown_motion",
    ),
)

updated_result = service.validate_and_update(
    updated_directives,
    scene_duration_seconds=8.0,
)

assert updated_result.is_valid is True

assert (
    updated_directives.status
    == EditingDirectiveStatus.READY
)

assert len(updated_directives.warnings) == 1


invalid_duration_result = service.validate(
    SceneEditingDirectives(
        scene_number=6,
    ),
    scene_duration_seconds=0.0,
)

assert invalid_duration_result.is_valid is False
assert invalid_duration_result.errors


print(
    "Editing Directive Validation Service "
    "tests completed successfully."
)