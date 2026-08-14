from __future__ import annotations

from src.models.genre_profile import (
    GenreEditingProfile,
    GenreProfile,
    GenreProfileStatus,
)
from src.services.genre_profile_registry_service import (
    GenreProfileRegistryService,
)

registry = GenreProfileRegistryService.with_default_profiles()

print(
    "Genre profiles:",
    len(registry.list_all()),
)

expected_genres = {
    "genre.default",
    "genre.horror",
    "genre.documentary",
    "genre.history",
    "genre.travel",
    "genre.top10",
    "genre.storytelling",
    "genre.medical",
    "genre.mystery",
    "genre.reaction",
    "genre.survival",
}

assert {profile.genre_id for profile in registry.list_all()} == expected_genres


horror = registry.get("genre.horror")

print("Horror voice:", horror.voice.voice_profile_id)
print(
    "Horror camera:",
    horror.editing.camera_preset_id,
)

assert horror.usable is True
assert horror.voice.voice_profile_id == "voice.horror_whisper"
assert horror.editing.camera_preset_id == "camera.slow_zoom_in"
assert horror.editing.music_preset_id == "music.horror_low_drone"
assert "visual.horror_dark_grade" in horror.editing.visual_preset_ids


documentary_result = registry.resolve("genre.documentary")

assert documentary_result.is_resolved is True
assert documentary_result.found_exact_match is True
assert documentary_result.used_fallback is False


unknown_result = registry.resolve("genre.unknown")

print(
    "Unknown fallback:",
    unknown_result.resolved_genre_id,
)

assert unknown_result.is_resolved is True
assert unknown_result.used_fallback is True
assert unknown_result.resolved_genre_id == "genre.default"
assert unknown_result.warning is not None


disabled_profile = GenreProfile(
    genre_id="genre.disabled_test",
    display_name="Disabled Test",
    status=GenreProfileStatus.DISABLED,
    fallback_genre_id="genre.horror",
)

registry.register(disabled_profile)

disabled_result = registry.resolve("genre.disabled_test")

assert disabled_result.is_resolved is True
assert disabled_result.used_fallback is True
assert disabled_result.resolved_genre_id == "genre.horror"
assert disabled_result.warning is not None


custom_profile = GenreProfile(
    genre_id="genre.finance",
    display_name="Finance",
    editing=GenreEditingProfile(
        camera_preset_id="camera.none",
        transition_in_preset_id=("transition.cut"),
        transition_out_preset_id=("transition.cut"),
        music_preset_id="music.none",
    ),
    tags=[
        "Finance",
        "Business",
        "finance",
    ],
)

registry.register(custom_profile)

assert registry.contains("genre.finance")

assert registry.get("genre.finance").tags == [
    "finance",
    "business",
]


replacement_profile = GenreProfile(
    genre_id="genre.finance",
    display_name="Finance Updated",
)

registry.register(
    replacement_profile,
    replace=True,
)

assert registry.get("genre.finance").display_name == "Finance Updated"


removed_profile = registry.unregister("genre.finance")

assert removed_profile.genre_id == "genre.finance"

assert not registry.contains("genre.finance")


try:
    registry.register(
        GenreProfile(
            genre_id="genre.horror",
            display_name="Duplicate Horror",
        )
    )
except ValueError:
    print("Duplicate genre successfully blocked.")
else:
    raise AssertionError("Duplicate genre registration should fail.")


try:
    registry.unregister("genre.default")
except ValueError:
    print("Default genre removal successfully blocked.")
else:
    raise AssertionError("Default genre must not be removable.")


try:
    GenreProfile(
        genre_id="genre.invalid",
        display_name="Invalid",
        fallback_genre_id="genre.invalid",
    )
except ValueError:
    print("Self fallback successfully blocked.")
else:
    raise AssertionError("A genre cannot fallback to itself.")


try:
    GenreEditingProfile(
        transition_in_preset_id=("transition.fade_black"),
        transition_out_preset_id=("transition.cut"),
        default_transition_duration_seconds=0.0,
    )
except ValueError:
    print("Missing transition duration " "successfully blocked.")
else:
    raise AssertionError("Non-cut genre transition requires duration.")


active_profiles = registry.list_all(
    active_only=True,
)

assert all(profile.usable for profile in active_profiles)


print("Genre Profile Registry Service tests " "completed successfully.")
