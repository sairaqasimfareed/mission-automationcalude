from __future__ import annotations

from src.models.voice_directives import (
    VoiceEmotion,
)
from src.models.voice_profile import (
    VoiceProfile,
    VoiceProfileStatus,
)
from src.services.voice_profile_registry_service import (
    VoiceProfileRegistryService,
)

registry = VoiceProfileRegistryService.with_default_profiles()

print(
    "Voice profiles:",
    len(registry.list_all()),
)

expected_profiles = {
    "voice.neutral_narrator",
    "voice.horror_whisper",
    "voice.documentary_authoritative",
    "voice.history_narrator",
    "voice.travel_energetic",
    "voice.top10_energetic",
    "voice.warm_storyteller",
}

assert {profile.profile_id for profile in registry.list_all()} == expected_profiles


horror = registry.get("voice.horror_whisper")

print(
    "Horror emotion:",
    horror.emotion,
)

assert horror.usable is True

assert horror.emotion == VoiceEmotion.SUSPENSEFUL

assert horror.default_speed == 0.9


exact_result = registry.resolve("voice.history_narrator")

assert exact_result.is_resolved is True
assert exact_result.found_exact_match is True
assert exact_result.used_fallback is False

assert exact_result.resolved_profile_id == "voice.history_narrator"


unknown_result = registry.resolve("voice.not_registered")

print(
    "Unknown fallback:",
    unknown_result.resolved_profile_id,
)

assert unknown_result.is_resolved is True
assert unknown_result.used_fallback is True

assert unknown_result.resolved_profile_id == "voice.neutral_narrator"

assert unknown_result.warning is not None


disabled_profile = VoiceProfile(
    profile_id="voice.disabled_test",
    display_name="Disabled Test",
    status=VoiceProfileStatus.DISABLED,
    fallback_profile_id=("voice.horror_whisper"),
)

registry.register(disabled_profile)

disabled_result = registry.resolve("voice.disabled_test")

assert disabled_result.is_resolved is True
assert disabled_result.used_fallback is True

assert disabled_result.resolved_profile_id == "voice.horror_whisper"

assert disabled_result.warning is not None


custom_profile = VoiceProfile(
    profile_id="voice.finance_narrator",
    display_name="Finance Narrator",
    tags=[
        "Finance",
        "Business",
        "finance",
    ],
)

registry.register(custom_profile)

assert registry.contains("voice.finance_narrator")

assert registry.get("voice.finance_narrator").tags == [
    "finance",
    "business",
]


replacement_profile = VoiceProfile(
    profile_id="voice.finance_narrator",
    display_name="Finance Narrator Updated",
)

registry.register(
    replacement_profile,
    replace=True,
)

assert registry.get("voice.finance_narrator").display_name == "Finance Narrator Updated"


removed = registry.unregister("voice.finance_narrator")

assert removed.profile_id == "voice.finance_narrator"

assert not registry.contains("voice.finance_narrator")


try:
    registry.register(
        VoiceProfile(
            profile_id=("voice.horror_whisper"),
            display_name="Duplicate Horror",
        )
    )
except ValueError:
    print("Duplicate voice profile " "successfully blocked.")
else:
    raise AssertionError("Duplicate registration should fail.")


try:
    registry.unregister("voice.neutral_narrator")
except ValueError:
    print("Default voice removal " "successfully blocked.")
else:
    raise AssertionError("Default voice profile " "must not be removed.")


try:
    VoiceProfile(
        profile_id="voice.invalid",
        display_name="Invalid",
        fallback_profile_id="voice.invalid",
    )
except ValueError:
    print("Self fallback successfully blocked.")
else:
    raise AssertionError("A voice profile cannot fallback " "to itself.")


no_fallback_result = registry.resolve(
    "voice.unregistered",
    allow_fallback=False,
)

assert no_fallback_result.is_resolved is False
assert no_fallback_result.used_fallback is False
assert no_fallback_result.warning is not None


active_profiles = registry.list_all(
    active_only=True,
)

assert all(profile.usable for profile in active_profiles)


print("Voice Profile Registry Service tests " "completed successfully.")
