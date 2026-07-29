from src.models.provider_preferences import (
    ProviderPreference,
)
from src.models.provider_profile import (
    ProviderCategory,
    ProviderHealthStatus,
    ProviderProfile,
)
from src.services.registry.provider_registry import (
    ProviderRegistry,
)
from src.services.selection.provider_selection_service import (
    ProviderSelectionRequest,
    ProviderSelectionService,
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

llm_disabled = ProviderProfile(
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
        llm_disabled,
        voice_main,
        llm_main,
    ]
)

service = ProviderSelectionService(registry)


preferred_result = service.select(
    ProviderSelectionRequest(
        category=ProviderCategory.LLM,
        required_capability="structured_json",
        preference=ProviderPreference(
            preferred_profile_id="llm-main",
        ),
    )
)

print(
    "Preferred selected:",
    preferred_result.selected_profile.profile_id,
)

assert preferred_result.selected_profile.profile_id == "llm-main"
assert preferred_result.used_preferred_profile is True
assert preferred_result.used_fallback_profile is False


fallback_result = service.select(
    ProviderSelectionRequest(
        category=ProviderCategory.LLM,
        required_capability="text_generation",
        preference=ProviderPreference(
            preferred_profile_id="llm-disabled",
            fallback_profile_ids=[
                "llm-backup",
            ],
        ),
    )
)

print(
    "Fallback selected:",
    fallback_result.selected_profile.profile_id,
)

assert fallback_result.selected_profile.profile_id == "llm-backup"
assert fallback_result.used_fallback_profile is True
assert len(fallback_result.warnings) == 1


automatic_result = service.select(
    ProviderSelectionRequest(
        category=ProviderCategory.LLM,
        required_capability="text_generation",
    )
)

print(
    "Automatic selected:",
    automatic_result.selected_profile.profile_id,
)

assert automatic_result.selected_profile.profile_id == "llm-main"


try:
    service.select(
        ProviderSelectionRequest(
            category=ProviderCategory.LLM,
            required_capability="video_generation",
        )
    )
except ValueError:
    print("Missing capability selection successfully blocked.")
else:
    raise AssertionError("Missing capability should not produce a provider.")


try:
    service.select(
        ProviderSelectionRequest(
            category=ProviderCategory.LLM,
            required_capability="text_generation",
            preference=ProviderPreference(
                preferred_profile_id="llm-disabled",
                lock_preferred_provider=True,
            ),
        )
    )
except ValueError:
    print("Unavailable locked provider successfully blocked.")
else:
    raise AssertionError("Locked unavailable provider should fail.")


try:
    service.select(
        ProviderSelectionRequest(
            category=ProviderCategory.LLM,
            preference=ProviderPreference(
                preferred_profile_id="voice-main",
                lock_preferred_provider=True,
            ),
        )
    )
except ValueError:
    print("Wrong-category locked provider successfully blocked.")
else:
    raise AssertionError("Wrong-category locked provider should fail.")


print("Provider Selection Service tests completed successfully.")
