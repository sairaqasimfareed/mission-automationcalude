from __future__ import annotations

from src.models.effect_registry import (
    EffectCategory,
    EffectPreset,
    EffectPresetStatus,
)
from src.services.effect_registry_service import (
    EffectRegistryService,
)

registry = EffectRegistryService.with_default_presets()

print(
    "Registered presets:",
    len(registry.list_all()),
)

assert registry.contains("camera.slow_zoom_in")

assert registry.contains("transition.fade_black")

assert registry.contains("visual.horror_dark_grade")

assert registry.contains("music.horror_low_drone")

assert registry.contains("sfx.door_creak")


camera_result = registry.resolve("camera.slow_zoom_in")

print(
    "Resolved camera:",
    camera_result.resolved_preset_id,
)

assert camera_result.is_resolved is True
assert camera_result.found_exact_match is True
assert camera_result.used_fallback is False
assert camera_result.preset is not None

assert camera_result.preset.category == EffectCategory.CAMERA


unknown_camera_result = registry.resolve("camera.unknown_motion")

print(
    "Unknown camera fallback:",
    unknown_camera_result.resolved_preset_id,
)

assert unknown_camera_result.is_resolved is True
assert unknown_camera_result.used_fallback is True
assert unknown_camera_result.resolved_preset_id == "camera.none"
assert unknown_camera_result.warning is not None


unknown_transition_result = registry.resolve("transition.unknown_transition")

assert unknown_transition_result.resolved_preset_id == "transition.cut"

assert unknown_transition_result.used_fallback is True


disabled_preset = EffectPreset(
    preset_id="visual.disabled_test",
    category=EffectCategory.VISUAL,
    display_name="Disabled Test",
    status=EffectPresetStatus.DISABLED,
    fallback_preset_id="visual.none",
)

registry.register(disabled_preset)

disabled_result = registry.resolve("visual.disabled_test")

assert disabled_result.is_resolved is True
assert disabled_result.used_fallback is True
assert disabled_result.resolved_preset_id == "visual.none"
assert disabled_result.warning is not None
assert "disabled" in (disabled_result.warning.lower())


no_fallback_result = registry.resolve(
    "camera.not_registered",
    allow_fallback=False,
)

assert no_fallback_result.is_resolved is False
assert no_fallback_result.used_fallback is False
assert no_fallback_result.warning is not None


camera_presets = registry.list_by_category(
    EffectCategory.CAMERA,
    active_only=True,
)

assert len(camera_presets) >= 2

assert all(preset.category == EffectCategory.CAMERA for preset in camera_presets)


custom_preset = EffectPreset(
    preset_id="camera.pan_diagonal",
    category=EffectCategory.CAMERA,
    display_name="Pan Diagonal",
    fallback_preset_id="camera.none",
    implementation={
        "motion": "pan",
        "direction": "diagonal",
    },
)

registry.register(custom_preset)

assert registry.contains("camera.pan_diagonal")

removed_preset = registry.unregister("camera.pan_diagonal")

assert removed_preset.preset_id == "camera.pan_diagonal"

assert not registry.contains("camera.pan_diagonal")


try:
    registry.register(
        EffectPreset(
            preset_id="camera.none",
            category=EffectCategory.CAMERA,
            display_name="Duplicate Camera None",
        )
    )
except ValueError:
    print("Duplicate preset successfully blocked.")
else:
    raise AssertionError("Duplicate preset registration should fail.")


try:
    EffectPreset(
        preset_id="visual.invalid",
        category=EffectCategory.CAMERA,
        display_name="Invalid Category",
    )
except ValueError:
    print("Mismatched category successfully blocked.")
else:
    raise AssertionError("Preset category mismatch should fail.")


bulk_results = registry.resolve_many(
    [
        "camera.slow_zoom_in",
        "transition.fade_black",
        "visual.unknown_effect",
    ]
)

assert len(bulk_results) == 3
assert bulk_results[0].found_exact_match is True
assert bulk_results[1].found_exact_match is True
assert bulk_results[2].used_fallback is True


new_camera_presets = [
    "camera.slow_zoom_out",
    "camera.fast_zoom_in",
    "camera.pan_left",
    "camera.pan_right",
]

new_transition_presets = [
    "transition.wipe_left",
    "transition.wipe_right",
    "transition.slide_left",
    "transition.circle_crop",
    "transition.pixelize",
]

new_visual_presets = [
    "visual.grayscale",
    "visual.sepia_tone",
    "visual.high_contrast_punch",
    "visual.film_grain_light",
    "visual.cool_blue_grade",
]

new_lut_presets = [
    "visual.lut_teal_orange",
    "visual.lut_bleach_bypass",
    "visual.lut_kodak_warm",
    "visual.lut_moody_desaturated",
    "visual.lut_vibrant_punch",
]

new_animation_presets = [
    "animation.slow_parallax_reverse",
    "animation.slow_pan_vertical",
    "animation.gentle_zoom_pulse",
]

all_new_presets = (
    new_camera_presets
    + new_transition_presets
    + new_visual_presets
    + new_lut_presets
    + new_animation_presets
)

for preset_id in all_new_presets:
    assert registry.contains(preset_id), f"Expected registered preset: {preset_id}"

    result = registry.resolve(preset_id)

    assert result.is_resolved is True
    assert result.found_exact_match is True
    assert result.used_fallback is False


for preset_id in new_lut_presets:
    lut_result = registry.resolve(preset_id)

    assert lut_result.preset is not None
    assert "lut" in lut_result.preset.tags


assert (
    len(
        registry.list_by_category(
            EffectCategory.CAMERA,
            active_only=True,
        )
    )
    == 6
)

assert (
    len(
        registry.list_by_category(
            EffectCategory.TRANSITION,
            active_only=True,
        )
    )
    == 8
)

assert (
    len(
        registry.list_by_category(
            EffectCategory.VISUAL,
            active_only=True,
        )
    )
    == 13
)

assert (
    len(
        registry.list_by_category(
            EffectCategory.ANIMATION,
            active_only=True,
        )
    )
    == 6
)


print("Effect Registry Service tests " "completed successfully.")
