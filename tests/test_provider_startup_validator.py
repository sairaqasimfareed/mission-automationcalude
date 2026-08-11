from __future__ import annotations

import pytest

from src.models.provider_profile import (
    ProviderCategory,
    ProviderHealthStatus,
    ProviderProfile,
)
from src.services.application_infrastructure_factory import (
    ApplicationInfrastructure,
    ApplicationInfrastructureFactory,
)
from src.services.health.provider_startup_validator import (
    ProviderStartupValidationResult,
    ProviderStartupValidator,
)
from src.services.secrets.provider_secret_manager import (
    InMemorySecretStore,
    ProviderSecretManager,
)


def _build_infrastructure(
    profile_specs: list[tuple[str, str, ProviderCategory, bool]],
) -> ApplicationInfrastructure:
    secret_store = InMemorySecretStore()
    secret_manager = ProviderSecretManager(secret_store=secret_store)

    profiles = [
        ProviderProfile(
            profile_id=profile_id,
            display_name=profile_id,
            provider_name=provider_name,
            category=category,
            enabled=enabled,
            secret_reference=secret_manager.create_secret(
                profile_id=profile_id,
                secret_value=f"secret-value-for-{profile_id}",
            ).secret_reference,
        )
        for profile_id, provider_name, category, enabled in profile_specs
    ]

    return ApplicationInfrastructureFactory(
        secret_store=secret_store,
    ).build(provider_profiles=profiles)


def test_validate_marks_valid_llm_profile_healthy() -> None:
    infrastructure = _build_infrastructure(
        [("provider.llm.openai", "openai", ProviderCategory.LLM, True)],
    )

    result = ProviderStartupValidator(infrastructure).validate()

    assert isinstance(result, ProviderStartupValidationResult)
    assert result.healthy_profile_ids == ["provider.llm.openai"]

    assert (
        infrastructure.provider_registry.get("provider.llm.openai").health_status
        == ProviderHealthStatus.HEALTHY
    )


def test_validate_raises_when_no_enabled_llm_profiles() -> None:
    infrastructure = _build_infrastructure(
        [("provider.voice.eleven", "elevenlabs", ProviderCategory.VOICE, True)],
    )

    with pytest.raises(ValueError, match="at least one enabled LLM"):
        ProviderStartupValidator(infrastructure).validate()


def test_validate_ignores_disabled_llm_profiles() -> None:
    infrastructure = _build_infrastructure(
        [("provider.llm.disabled", "openai", ProviderCategory.LLM, False)],
    )

    with pytest.raises(ValueError, match="at least one enabled LLM"):
        ProviderStartupValidator(infrastructure).validate()


def test_validate_raises_when_every_llm_profile_fails() -> None:
    infrastructure = _build_infrastructure(
        [
            (
                "provider.llm.bad",
                "not-a-real-provider",
                ProviderCategory.LLM,
                True,
            ),
        ],
    )

    with pytest.raises(ValueError, match="No configured LLM provider passed"):
        ProviderStartupValidator(infrastructure).validate()


def test_validate_succeeds_when_at_least_one_llm_profile_is_healthy() -> None:
    infrastructure = _build_infrastructure(
        [
            ("provider.llm.good", "openai", ProviderCategory.LLM, True),
            (
                "provider.llm.bad",
                "not-a-real-provider",
                ProviderCategory.LLM,
                True,
            ),
        ],
    )

    result = ProviderStartupValidator(infrastructure).validate()

    assert result.healthy_profile_ids == ["provider.llm.good"]
    assert len(result.results) == 2
