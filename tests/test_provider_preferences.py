from src.models.provider_preferences import (
    ProviderPreference,
    ProviderPreferences,
)

voice_preference = ProviderPreference(
    preferred_profile_id="voice-main",
    fallback_profile_ids=[
        "voice-backup",
        " voice-secondary ",
        "voice-backup",
        "",
    ],
    auto_select=True,
    lock_preferred_provider=False,
)

print(
    "Preferred voice provider:",
    voice_preference.preferred_profile_id,
)
print(
    "Voice fallbacks:",
    voice_preference.fallback_profile_ids,
)

assert voice_preference.preferred_profile_id == "voice-main"
assert voice_preference.fallback_profile_ids == [
    "voice-backup",
    "voice-secondary",
]


preferences = ProviderPreferences(
    voice=voice_preference,
    video=ProviderPreference(
        preferred_profile_id="video-main",
        fallback_profile_ids=[
            "video-backup",
        ],
        auto_select=False,
        lock_preferred_provider=True,
    ),
)

print(
    "Video provider:",
    preferences.video.preferred_profile_id,
)
print(
    "Video provider locked:",
    preferences.video.lock_preferred_provider,
)

assert preferences.voice == voice_preference
assert preferences.video.preferred_profile_id == "video-main"
assert preferences.video.auto_select is False
assert preferences.video.lock_preferred_provider is True

assert preferences.llm.auto_select is True
assert preferences.image.preferred_profile_id is None


serialized = preferences.model_dump_json()
restored = ProviderPreferences.model_validate_json(serialized)

assert restored == preferences
assert restored.schema_version == "1.0"

print("Provider Preferences tests completed successfully.")
