from __future__ import annotations

from src.models.provider_profile import ProviderCategory, ProviderProfile
from src.services.factory.provider_factory import ProviderFactory
from src.services.health.llm_provider_startup_checker import (
    LLMProviderStartupChecker,
)
from src.services.registry.provider_registry import ProviderRegistry
from src.services.secrets.provider_secret_manager import (
    InMemorySecretStore,
    ProviderSecretManager,
)


def _llm_profile_and_factory(
    *,
    provider_name: str = "openai",
) -> tuple[ProviderProfile, ProviderFactory]:
    secret_store = InMemorySecretStore()
    secret_manager = ProviderSecretManager(secret_store=secret_store)

    secret = secret_manager.create_secret(
        profile_id="provider.llm.test",
        secret_value="sk-test-secret-key",
    )

    profile = ProviderProfile(
        profile_id="provider.llm.test",
        display_name="Test LLM",
        provider_name=provider_name,
        category=ProviderCategory.LLM,
        enabled=True,
        secret_reference=secret.secret_reference,
    )

    factory = ProviderFactory(
        registry=ProviderRegistry(profiles=[profile]),
        secret_manager=secret_manager,
    )

    return profile, factory


def test_check_succeeds_for_valid_llm_profile() -> None:
    profile, factory = _llm_profile_and_factory()
    checker = LLMProviderStartupChecker(factory)

    healthy, message = checker.check(profile)

    assert healthy is True
    assert "constructed successfully" in message


def test_check_fails_for_unsupported_provider_name() -> None:
    profile, factory = _llm_profile_and_factory(
        provider_name="not-a-real-provider",
    )
    checker = LLMProviderStartupChecker(factory)

    healthy, message = checker.check(profile)

    assert healthy is False
    assert "ValueError" in message


def test_check_skips_non_llm_profiles() -> None:
    secret_store = InMemorySecretStore()
    secret_manager = ProviderSecretManager(secret_store=secret_store)

    secret = secret_manager.create_secret(
        profile_id="provider.voice.test",
        secret_value="voice-test-secret-key",
    )

    profile = ProviderProfile(
        profile_id="provider.voice.test",
        display_name="Test Voice",
        provider_name="elevenlabs",
        category=ProviderCategory.VOICE,
        enabled=True,
        secret_reference=secret.secret_reference,
    )

    factory = ProviderFactory(
        registry=ProviderRegistry(profiles=[profile]),
        secret_manager=secret_manager,
    )

    checker = LLMProviderStartupChecker(factory)

    healthy, message = checker.check(profile)

    assert healthy is True
    assert "only covers LLM" in message
