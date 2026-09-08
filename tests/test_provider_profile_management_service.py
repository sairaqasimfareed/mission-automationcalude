from __future__ import annotations

from src.models.provider_profile import ProviderCategory, ProviderHealthStatus
from src.models.provider_profile_management import ProviderProfileUpsertCommand
from src.services.provider_profile_management_service import (
    ProviderProfileManagementService,
)
from src.services.registry.provider_profile_repository import (
    InMemoryProviderProfileRepository,
)
from src.services.registry.provider_registry import ProviderRegistry
from src.services.secrets.provider_secret_manager import (
    InMemorySecretStore,
    ProviderSecretManager,
)


def build_service(
    repository: InMemoryProviderProfileRepository,
) -> ProviderProfileManagementService:
    return ProviderProfileManagementService(
        registry=ProviderRegistry(),
        repository=repository,
        secret_manager=ProviderSecretManager(InMemorySecretStore()),
    )


shared_repository = InMemoryProviderProfileRepository()
service = build_service(shared_repository)

assert service.load() == []


# Creating an enabled profile without a secret must fail before anything
# is persisted.
try:
    service.upsert_profile(
        ProviderProfileUpsertCommand(
            profile_id="llm-main",
            display_name="LLM Main",
            provider_name="OpenAI",
            category=ProviderCategory.LLM,
            enabled=True,
        )
    )
except ValueError:
    print("Enable-without-secret create successfully blocked.")
else:
    raise AssertionError("Creating an enabled profile with no secret should fail.")

assert shared_repository.load_all() == []


created = service.upsert_profile(
    ProviderProfileUpsertCommand(
        profile_id="llm-main",
        display_name="LLM Main",
        provider_name="OpenAI",
        category=ProviderCategory.LLM,
        enabled=True,
        secret_value="sk-test-secret-123456",
        daily_budget_usd=5.0,
        monthly_budget_usd=50.0,
    )
)

print("Created profile:", created.profile_id, created.masked_secret)

assert created.has_secret is True
assert created.masked_secret is not None
assert created.enabled is True
assert created.health_status == ProviderHealthStatus.UNKNOWN

persisted = shared_repository.load_all()

assert len(persisted) == 1
assert persisted[0].profile_id == "llm-main"
assert persisted[0].secret_reference is not None

original_secret_reference = persisted[0].secret_reference


# Update without touching the secret must preserve it.
updated = service.upsert_profile(
    ProviderProfileUpsertCommand(
        profile_id="llm-main",
        display_name="LLM Main (renamed)",
        provider_name="OpenAI",
        category=ProviderCategory.LLM,
        enabled=True,
        daily_budget_usd=5.0,
        monthly_budget_usd=50.0,
    )
)

assert updated.display_name == "LLM Main (renamed)"
assert shared_repository.load_all()[0].secret_reference == original_secret_reference


# Update with a new secret value must replace the stored secret, not
# create a second one.
replaced = service.upsert_profile(
    ProviderProfileUpsertCommand(
        profile_id="llm-main",
        display_name="LLM Main (renamed)",
        provider_name="OpenAI",
        category=ProviderCategory.LLM,
        enabled=True,
        secret_value="sk-replaced-secret-654321",
        daily_budget_usd=5.0,
        monthly_budget_usd=50.0,
    )
)

assert shared_repository.load_all()[0].secret_reference == original_secret_reference
assert replaced.masked_secret != created.masked_secret


# A second, disabled profile with no secret.
service.upsert_profile(
    ProviderProfileUpsertCommand(
        profile_id="voice-main",
        display_name="Voice Main",
        provider_name="ElevenLabs",
        category=ProviderCategory.VOICE,
        enabled=False,
    )
)

try:
    service.set_enabled("voice-main", True)
except ValueError:
    print("Enable-without-secret toggle successfully blocked.")
else:
    raise AssertionError("Enabling a secret-less profile should fail.")

healthy_result = service.check_health("llm-main")

print("Health result:", healthy_result.status, healthy_result.message)

assert healthy_result.healthy is True
assert healthy_result.status == ProviderHealthStatus.HEALTHY

# voice-main is disabled (ProviderProfile's own validation forbids an
# enabled profile with no secret, so MISCONFIGURED is unreachable here -
# DISABLED is checked first).
disabled_secretless_result = service.check_health("voice-main")

assert disabled_secretless_result.healthy is False
assert disabled_secretless_result.status == ProviderHealthStatus.DISABLED

disabled = service.set_enabled("llm-main", False)

assert disabled.enabled is False

persisted_llm_profile = next(
    profile
    for profile in shared_repository.load_all()
    if profile.profile_id == "llm-main"
)

assert persisted_llm_profile.enabled is False

disabled_health_result = service.check_health("llm-main")

assert disabled_health_result.status == ProviderHealthStatus.DISABLED


# Real-world finding (found via a live Provider Manager repro, not
# theorized): llm-main is now stuck exactly as it would be after a
# user disables a profile then clicks "Test configuration" before
# ever re-enabling it - check_health() just set health_status to
# DISABLED as a side effect. ProviderProfile's own model validator
# forbids enabled=True while health_status is DISABLED, and nothing
# else in this service ever moves health_status off DISABLED again -
# without the fix below, re-enabling here would raise ValueError and
# permanently trap this profile. upsert_profile() must give a stale
# DISABLED status a fresh UNKNOWN when the command is genuinely
# re-enabling the profile, so a real "check Enabled, Save" action in
# the GUI succeeds instead of deadlocking.
reenabled_llm_profile = service.upsert_profile(
    ProviderProfileUpsertCommand(
        profile_id="llm-main",
        display_name="LLM Main (renamed)",
        provider_name="OpenAI",
        category=ProviderCategory.LLM,
        enabled=True,
        daily_budget_usd=5.0,
        monthly_budget_usd=50.0,
    )
)

assert reenabled_llm_profile.enabled is True
assert reenabled_llm_profile.health_status == ProviderHealthStatus.UNKNOWN

persisted_reenabled_profile = next(
    profile
    for profile in shared_repository.load_all()
    if profile.profile_id == "llm-main"
)

assert persisted_reenabled_profile.enabled is True
assert persisted_reenabled_profile.health_status == ProviderHealthStatus.UNKNOWN

# A genuinely healthy real check must still work normally afterward -
# the reset is a one-time unstick, not a permanent short-circuit.
reenabled_health_result = service.check_health("llm-main")

assert reenabled_health_result.status == ProviderHealthStatus.HEALTHY


all_profiles = service.list_profiles()

assert {profile.profile_id for profile in all_profiles} == {"llm-main", "voice-main"}


service.delete_profile("llm-main")

assert not any(profile.profile_id == "llm-main" for profile in service.list_profiles())
assert not any(
    profile.profile_id == "llm-main" for profile in shared_repository.load_all()
)

try:
    service.get_profile("llm-main")
except KeyError:
    print("Deleted profile successfully blocked from get_profile().")
else:
    raise AssertionError("Deleted profile should no longer be retrievable.")


# A fresh service instance pointed at the same repository must reseed
# its registry from durable storage on load().
reloaded_service = build_service(shared_repository)
reloaded_profiles = reloaded_service.load()

assert [profile.profile_id for profile in reloaded_profiles] == ["voice-main"]


# --- Google Flow External UI Automation, GF-13: EXTERNAL_UI_VIDEO
# authenticates via browser_profile_reference, never secret_value. ---

flow_repository = InMemoryProviderProfileRepository()
flow_service = build_service(flow_repository)

try:
    flow_service.upsert_profile(
        ProviderProfileUpsertCommand(
            profile_id="flow-primary",
            display_name="Flow Primary",
            provider_name="Google Flow",
            category=ProviderCategory.EXTERNAL_UI_VIDEO,
            enabled=True,
            secret_value="this-is-not-how-flow-authenticates",
        )
    )
except ValueError:
    print(
        "Enabling a Flow profile with only secret_value (no "
        "browser_profile_reference) successfully blocked."
    )
else:
    raise AssertionError(
        "An enabled Flow profile requires browser_profile_reference, "
        "not secret_value."
    )


created_flow_profile = flow_service.upsert_profile(
    ProviderProfileUpsertCommand(
        profile_id="flow-primary",
        display_name="Flow Primary",
        provider_name="Google Flow",
        category=ProviderCategory.EXTERNAL_UI_VIDEO,
        enabled=True,
        browser_profile_reference="flow_profiles/flow-primary",
    )
)

assert created_flow_profile.browser_profile_reference == "flow_profiles/flow-primary"
assert created_flow_profile.has_secret is False
assert created_flow_profile.enabled is True


# set_enabled() must not hard-require a secret for a Flow profile -
# the GF-13-found gap this pass fixed.
disabled_flow_profile = flow_service.set_enabled("flow-primary", False)
assert disabled_flow_profile.enabled is False

reenabled_flow_profile = flow_service.set_enabled("flow-primary", True)
assert reenabled_flow_profile.enabled is True


try:
    flow_service.upsert_profile(
        ProviderProfileUpsertCommand(
            profile_id="flow-secondary",
            display_name="Flow Secondary",
            provider_name="Google Flow",
            category=ProviderCategory.EXTERNAL_UI_VIDEO,
            enabled=True,
        )
    )
except ValueError:
    print("Enabling a Flow profile with no credential at all " "successfully blocked.")
else:
    raise AssertionError(
        "An enabled Flow profile requires a browser_profile_reference."
    )


print("Provider Profile Management Service tests completed successfully.")
