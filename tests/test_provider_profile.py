from pydantic import ValidationError

from src.models.provider_profile import (
    ProviderCategory,
    ProviderHealthStatus,
    ProviderProfile,
)


profile = ProviderProfile(
    profile_id="openai-main",
    display_name="OpenAI Main",
    provider_name="OpenAI",
    category=ProviderCategory.LLM,
    enabled=True,
    priority=1,
    secret_reference="secret://providers/openai-main",
    default_model="gpt-model",
    daily_budget_usd=5.0,
    monthly_budget_usd=100.0,
    health_status=ProviderHealthStatus.HEALTHY,
    capabilities=[
        "text_generation",
        " structured_json ",
        "text_generation",
        "",
    ],
)

print("Profile:", profile.display_name)
print("Category:", profile.category)
print("Health:", profile.health_status)
print("Capabilities:", profile.capabilities)
print("Usable:", profile.usable)

assert profile.profile_id == "openai-main"
assert profile.category == ProviderCategory.LLM
assert profile.priority == 1
assert profile.capabilities == [
    "text_generation",
    "structured_json",
]
assert profile.supports("TEXT_GENERATION")
assert profile.usable is True


disabled_profile = ProviderProfile(
    profile_id="video-backup",
    display_name="Video Backup",
    provider_name="Video Provider",
    category=ProviderCategory.VIDEO,
    enabled=False,
)

assert disabled_profile.usable is False


try:
    ProviderProfile(
        profile_id="voice-main",
        display_name="Voice Main",
        provider_name="Voice Provider",
        category=ProviderCategory.VOICE,
        enabled=True,
    )
except ValidationError:
    print(
        "Enabled profile without secret successfully blocked."
    )
else:
    raise AssertionError(
        "Enabled profile must require a secret reference."
    )


try:
    ProviderProfile(
        profile_id="music-main",
        display_name="Music Main",
        provider_name="Music Provider",
        category=ProviderCategory.MUSIC,
        daily_budget_usd=20.0,
        monthly_budget_usd=10.0,
    )
except ValidationError:
    print("Invalid provider budget successfully blocked.")
else:
    raise AssertionError(
        "Daily budget above monthly budget should fail."
    )


serialized = profile.model_dump_json()
restored = ProviderProfile.model_validate_json(serialized)

assert restored == profile
assert restored.schema_version == "1.0"

print("Provider Profile tests completed successfully.")