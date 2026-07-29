from src.models.provider_profile import (
    ProviderCategory,
    ProviderHealthStatus,
    ProviderProfile,
)
from src.services.registry.provider_registry import (
    ProviderRegistry,
)


llm_main = ProviderProfile(
    profile_id="llm-main",
    display_name="LLM Main",
    provider_name="OpenAI",
    category=ProviderCategory.LLM,
    enabled=True,
    priority=1,
    secret_reference="secret://llm-main",
    health_status=ProviderHealthStatus.HEALTHY,
    capabilities=[
        "text_generation",
        "structured_json",
    ],
)

llm_backup = ProviderProfile(
    profile_id="llm-backup",
    display_name="LLM Backup",
    provider_name="Gemini",
    category=ProviderCategory.LLM,
    enabled=True,
    priority=2,
    secret_reference="secret://llm-backup",
    health_status=ProviderHealthStatus.DEGRADED,
    capabilities=[
        "text_generation",
    ],
)

disabled_llm = ProviderProfile(
    profile_id="llm-disabled",
    display_name="LLM Disabled",
    provider_name="Anthropic",
    category=ProviderCategory.LLM,
    enabled=False,
    priority=3,
    capabilities=[
        "text_generation",
    ],
)

voice_main = ProviderProfile(
    profile_id="voice-main",
    display_name="Voice Main",
    provider_name="ElevenLabs",
    category=ProviderCategory.VOICE,
    enabled=True,
    priority=1,
    secret_reference="secret://voice-main",
    health_status=ProviderHealthStatus.HEALTHY,
    capabilities=[
        "voice_generation",
    ],
)


registry = ProviderRegistry(
    profiles=[
        llm_backup,
        voice_main,
        disabled_llm,
        llm_main,
    ]
)

print("Registry count:", registry.count)
print(
    "All profiles:",
    [profile.profile_id for profile in registry.list_all()],
)

assert registry.count == 4
assert registry.contains("llm-main")
assert registry.get("llm-main") == llm_main

llm_profiles = registry.list_by_category(
    ProviderCategory.LLM
)

assert [
    profile.profile_id
    for profile in llm_profiles
] == [
    "llm-main",
    "llm-backup",
    "llm-disabled",
]


enabled_llm_profiles = registry.list_by_category(
    ProviderCategory.LLM,
    enabled_only=True,
)

assert [
    profile.profile_id
    for profile in enabled_llm_profiles
] == [
    "llm-main",
    "llm-backup",
]


usable_llm_profiles = registry.list_by_category(
    ProviderCategory.LLM,
    usable_only=True,
)

assert [
    profile.profile_id
    for profile in usable_llm_profiles
] == [
    "llm-main",
    "llm-backup",
]


structured_profiles = registry.find_supporting(
    ProviderCategory.LLM,
    "STRUCTURED_JSON",
)

assert [
    profile.profile_id
    for profile in structured_profiles
] == [
    "llm-main",
]


try:
    registry.register(llm_main)
except ValueError:
    print("Duplicate profile successfully blocked.")
else:
    raise AssertionError(
        "Duplicate profile registration should fail."
    )


replacement = llm_main.model_copy(
    update={
        "display_name": "Updated LLM Main",
        "priority": 5,
    }
)

registry.register(
    replacement,
    replace=True,
)

assert (
    registry.get("llm-main").display_name
    == "Updated LLM Main"
)


removed = registry.unregister("llm-disabled")

assert removed.profile_id == "llm-disabled"
assert registry.count == 3
assert not registry.contains("llm-disabled")


try:
    registry.get("missing-profile")
except KeyError:
    print("Missing profile successfully blocked.")
else:
    raise AssertionError(
        "Missing profile lookup should fail."
    )


print("Provider Registry tests completed successfully.")