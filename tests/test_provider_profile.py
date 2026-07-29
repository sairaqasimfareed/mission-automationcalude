from src.models.provider_profile import (
    ProviderProfile,
)

profile = ProviderProfile(
    profile_id="gemini-main",

    display_name="Gemini Main",

    provider_type="gemini",

    api_key="dummy",

    model_name="gemini-2.5-pro",

    supports_llm=True,
)

assert profile.enabled

assert profile.supports_llm

assert profile.provider_type == "gemini"

serialized = profile.model_dump_json()

restored = ProviderProfile.model_validate_json(
    serialized
)

assert restored == profile

print(
    "Provider Profile tests completed successfully."
)