from __future__ import annotations

from src.models.effect_registry import (
    EffectCategory,
    EffectPreset,
)
from src.models.genre_profile import (
    GenreEditingProfile,
    GenreProfile,
    GenreProfileStatus,
)
from src.models.genre_profile_validation import (
    GenreValidationCode,
)
from src.services.effect_registry_service import (
    EffectRegistryService,
)
from src.services.genre_profile_registry_service import (
    GenreProfileRegistryService,
)
from src.services.genre_profile_validation_service import (
    GenreProfileValidationService,
)


effect_registry = (
    EffectRegistryService
    .with_default_presets()
)

genre_registry = (
    GenreProfileRegistryService
    .with_default_profiles()
)

service = GenreProfileValidationService(
    effect_registry=effect_registry,
)


horror_profile = genre_registry.get(
    "genre.horror"
)

horror_result = service.validate_profile(
    horror_profile
)

print(
    "Horror valid:",
    horror_result.is_valid,
)

print(
    "Horror fallbacks:",
    horror_result.fallback_count,
)

assert horror_result.is_valid is True
assert horror_result.is_production_ready is True
assert horror_result.unresolved_count == 0
assert horror_result.fallback_count == 0
assert horror_result.exact_match_count > 0
assert horror_result.errors == []


# Some built-in profiles currently reference presets
# which are intentionally not registered yet.
documentary_profile = genre_registry.get(
    "genre.documentary"
)

documentary_result = (
    service.validate_profile(
        documentary_profile
    )
)

assert documentary_result.is_valid is True
assert documentary_result.is_production_ready is True

# Missing voice and thumbnail profiles are not checked here;
# this sprint validates editing references only.


unknown_effect_profile = GenreProfile(
    genre_id="genre.unknown_effect_test",
    display_name="Unknown Effect Test",
    editing=GenreEditingProfile(
        camera_preset_id=(
            "camera.not_registered"
        ),
        transition_in_preset_id=(
            "transition.cut"
        ),
        transition_out_preset_id=(
            "transition.cut"
        ),
        visual_preset_ids=[
            "visual.not_registered",
        ],
        music_preset_id="music.none",
        subtitle_preset_id=(
            "subtitle.default"
        ),
    ),
)

unknown_result = service.validate_profile(
    unknown_effect_profile
)

print(
    "Unknown fallback count:",
    unknown_result.fallback_count,
)

assert unknown_result.is_valid is True
assert unknown_result.is_production_ready is True
assert unknown_result.fallback_count == 2
assert unknown_result.unresolved_count == 0

assert len(
    [
        issue
        for issue in unknown_result.warnings
        if (
            issue.code
            == GenreValidationCode
            .EFFECT_FALLBACK_USED
        )
    ]
) == 2


disabled_profile = GenreProfile(
    genre_id="genre.disabled_validation",
    display_name="Disabled Validation",
    status=GenreProfileStatus.DISABLED,
)

disabled_result = service.validate_profile(
    disabled_profile
)

assert disabled_result.is_valid is False
assert disabled_result.is_production_ready is False

assert any(
    issue.code
    == GenreValidationCode
    .UNUSABLE_GENRE_PROFILE
    for issue in disabled_result.errors
)


effect_registry.register(
    EffectPreset(
        preset_id="visual.extra_test",
        category=EffectCategory.VISUAL,
        display_name="Extra Test",
        fallback_preset_id="visual.none",
    )
)

excessive_profile = GenreProfile(
    genre_id="genre.excessive_test",
    display_name="Excessive Test",
    editing=GenreEditingProfile(
        visual_preset_ids=[
            "visual.vignette_soft",
            "visual.horror_dark_grade",
            "visual.extra_test",
        ],
        maximum_active_effects=2,
    ),
)

excessive_result = service.validate_profile(
    excessive_profile
)

assert excessive_result.is_valid is True

assert any(
    issue.code
    == GenreValidationCode
    .EXCESSIVE_DEFAULT_EFFECTS
    for issue in excessive_result.warnings
)


registry_result = service.validate_registry(
    genre_registry
)

print(
    "Registry valid:",
    registry_result.is_valid,
)

print(
    "Production ready:",
    registry_result.production_ready_count,
)

assert registry_result.is_valid is True

assert (
    registry_result.profile_count
    == len(genre_registry.list_all())
)

assert (
    registry_result.production_ready_count
    == registry_result.profile_count
)


print(
    "Genre Profile Validation Service "
    "tests completed successfully."
)