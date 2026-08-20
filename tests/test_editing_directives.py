from __future__ import annotations

from src.models.editing_directives import (
    AnimationDirective,
    CameraDirective,
    DirectiveIntensity,
    DirectiveTimingMode,
    EditingDirectiveStatus,
    MusicDirective,
    SceneEditingDirectives,
    SoundEffectDirective,
    SubtitleDirective,
    TransitionDirective,
    VisualEffectDirective,
)

directives = SceneEditingDirectives(
    scene_number=1,
    genre_preset_id="genre.horror",
    camera=CameraDirective(
        preset_id="camera.slow_zoom_in",
        intensity=DirectiveIntensity.LOW,
        start_offset_seconds=0.0,
        end_offset_seconds=8.0,
        zoom_start=1.0,
        zoom_end=1.08,
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
            preset_id="visual.horror_dark_grade",
            intensity=DirectiveIntensity.MEDIUM,
            timing_mode=(DirectiveTimingMode.FULL_SCENE),
        ),
        VisualEffectDirective(
            preset_id="visual.vignette_soft",
            intensity=DirectiveIntensity.LOW,
        ),
    ],
    animations=[
        AnimationDirective(
            preset_id="animation.slow_parallax",
            duration_seconds=8.0,
        ),
    ],
    music=MusicDirective(
        preset_id="music.horror_low_drone",
        volume_percent=25.0,
        duck_under_voice=True,
    ),
    sound_effects=[
        SoundEffectDirective(
            preset_id="sfx.door_creak",
            timing_mode=(DirectiveTimingMode.ABSOLUTE_SECONDS),
            start_offset_seconds=4.5,
            volume_percent=70.0,
        ),
        SoundEffectDirective(
            preset_id="sfx.heartbeat_low",
            timing_mode=(DirectiveTimingMode.RELATIVE_PERCENT),
            relative_position_percent=75.0,
            volume_percent=45.0,
        ),
    ],
    subtitles=SubtitleDirective(
        preset_id="subtitle.cinematic",
        animation_preset_id=("animation.subtitle_fade"),
        maximum_words_per_line=7,
    ),
    status=EditingDirectiveStatus.READY,
)

print("Genre:", directives.genre_preset_id)
print("Camera:", directives.camera.preset_id)
print(
    "Active effects:",
    directives.active_effect_count,
)

assert directives.scene_number == 1
assert directives.genre_preset_id == "genre.horror"
assert directives.camera.preset_id == "camera.slow_zoom_in"
assert directives.transition_in.preset_id == "transition.fade_black"
assert directives.music.preset_id == "music.horror_low_drone"
assert len(directives.visual_effects) == 2
assert len(directives.sound_effects) == 2
assert directives.active_effect_count == 5


try:
    CameraDirective(
        preset_id="slow_zoom_in",
    )
except ValueError:
    print("Invalid camera registry ID " "successfully blocked.")
else:
    raise AssertionError("Camera registry ID without prefix " "should fail.")


try:
    TransitionDirective(
        preset_id="transition.fade_black",
        duration_seconds=0.0,
    )
except ValueError:
    print("Zero-duration fade transition " "successfully blocked.")
else:
    raise AssertionError("Non-cut transition requires duration.")


try:
    SoundEffectDirective(
        preset_id="sfx.impact_hit",
        timing_mode=(DirectiveTimingMode.RELATIVE_PERCENT),
    )
except ValueError:
    print("Missing relative SFX position " "successfully blocked.")
else:
    raise AssertionError("Relative SFX timing requires " "a percentage.")


try:
    SceneEditingDirectives(
        scene_number=2,
        visual_effects=[
            VisualEffectDirective(
                preset_id="visual.vignette_soft",
            ),
            VisualEffectDirective(
                preset_id="visual.vignette_soft",
            ),
        ],
    )
except ValueError:
    print("Duplicate visual directives " "successfully blocked.")
else:
    raise AssertionError("Duplicate visual effects should fail.")


default_directives = SceneEditingDirectives(
    scene_number=3,
)

assert default_directives.camera.preset_id == "camera.none"
assert default_directives.transition_in.preset_id == "transition.cut"
assert default_directives.music.preset_id == "music.none"
assert default_directives.active_effect_count == 0


print("Editing Directive model tests " "completed successfully.")
