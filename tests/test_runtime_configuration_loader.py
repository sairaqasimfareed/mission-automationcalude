from __future__ import annotations

import pytest

from src.config.settings import Settings
from src.models.provider_profile import ProviderCategory
from src.providers.dry_run_voice_provider import DryRunVoiceProvider
from src.services.genre_profile_registry_service import (
    GenreProfileRegistryService,
)
from src.services.runtime_configuration_loader import (
    RuntimeConfiguration,
    RuntimeConfigurationLoader,
)
from src.services.secrets.provider_secret_manager import (
    InMemorySecretStore,
    ProviderSecretManager,
)


def _settings(**overrides: object) -> Settings:
    """Build a Settings instance isolated from the real environment."""

    defaults: dict[str, object] = {
        "OPENAI_API_KEY": "",
        "CLAUDE_API_KEY": "",
        "GOOGLE_API_KEY": "",
        "ELEVENLABS_API_KEY": "",
        "MISSION_AUTOMATION_DRY_RUN": True,
    }

    defaults.update(overrides)

    return Settings(**defaults)  # type: ignore[arg-type]


def test_load_in_dry_run_with_no_keys_builds_placeholder_profile() -> None:
    loader = RuntimeConfigurationLoader(settings=_settings())

    configuration = loader.load()

    assert isinstance(configuration, RuntimeConfiguration)
    assert len(configuration.provider_profiles) == 1

    profile = configuration.provider_profiles[0]

    assert profile.profile_id == "provider.llm.dry_run"
    assert profile.category == ProviderCategory.LLM
    assert profile.enabled is True


def test_load_in_dry_run_still_uses_real_keys_when_present() -> None:
    loader = RuntimeConfigurationLoader(
        settings=_settings(OPENAI_API_KEY="sk-real-openai-key"),
    )

    configuration = loader.load()

    profile_ids = [profile.profile_id for profile in configuration.provider_profiles]

    assert profile_ids == ["provider.llm.openai"]


def test_load_builds_one_profile_per_configured_key() -> None:
    loader = RuntimeConfigurationLoader(
        settings=_settings(
            OPENAI_API_KEY="sk-real-openai-key",
            CLAUDE_API_KEY="sk-real-claude-key",
        ),
    )

    configuration = loader.load()

    profile_ids = {profile.profile_id for profile in configuration.provider_profiles}

    assert profile_ids == {
        "provider.llm.openai",
        "provider.llm.anthropic",
    }


def test_load_stores_resolvable_secret_for_each_profile() -> None:
    loader = RuntimeConfigurationLoader(
        settings=_settings(OPENAI_API_KEY="sk-real-openai-key"),
    )

    configuration = loader.load()

    secret_manager = ProviderSecretManager(
        secret_store=configuration.secret_store,
    )

    profile = configuration.provider_profiles[0]

    assert profile.secret_reference is not None
    assert secret_manager.resolve_secret(profile.secret_reference) == (
        "sk-real-openai-key"
    )


def test_load_outside_dry_run_without_keys_raises() -> None:
    loader = RuntimeConfigurationLoader(
        settings=_settings(MISSION_AUTOMATION_DRY_RUN=False),
    )

    with pytest.raises(ValueError, match="No LLM provider API key"):
        loader.load()


def test_load_outside_dry_run_raises_for_voice_provider() -> None:
    loader = RuntimeConfigurationLoader(
        settings=_settings(
            OPENAI_API_KEY="sk-real-openai-key",
            MISSION_AUTOMATION_DRY_RUN=False,
        ),
    )

    with pytest.raises(ValueError, match="voice-provider adapter"):
        loader.load()


def test_load_in_dry_run_uses_dry_run_voice_provider() -> None:
    loader = RuntimeConfigurationLoader(settings=_settings())

    configuration = loader.load()

    assert len(configuration.voice_providers) == 1
    assert isinstance(configuration.voice_providers[0], DryRunVoiceProvider)


def test_load_includes_default_voice_profile() -> None:
    loader = RuntimeConfigurationLoader(settings=_settings())

    configuration = loader.load()

    profile_ids = [profile.profile_id for profile in configuration.voice_profiles]

    assert profile_ids == ["voice.neutral_narrator"]


def test_load_uses_default_genre_registry() -> None:
    loader = RuntimeConfigurationLoader(settings=_settings())

    configuration = loader.load()

    assert isinstance(configuration.genre_registry, GenreProfileRegistryService)


def test_load_synchronizes_advanced_settings_dry_run_with_settings() -> None:
    dry_run_configuration = RuntimeConfigurationLoader(
        settings=_settings(MISSION_AUTOMATION_DRY_RUN=True),
    ).load()

    assert dry_run_configuration.advanced_settings.dry_run is True

    # Outside dry-run, load() cannot yet succeed at all: no concrete
    # VoiceProvider adapter exists, so voice-provider construction
    # fails fast before AdvancedSettings.dry_run=False is ever
    # observable from a completed RuntimeConfiguration. This is
    # covered separately by
    # test_load_outside_dry_run_raises_for_voice_provider.


def test_load_disables_checkpoint_persistence_by_default() -> None:
    loader = RuntimeConfigurationLoader(settings=_settings())

    configuration = loader.load()

    assert configuration.checkpoint_storage_root is None


def test_loader_uses_injected_secret_store() -> None:
    secret_store = InMemorySecretStore()

    loader = RuntimeConfigurationLoader(
        settings=_settings(),
        secret_store=secret_store,
    )

    configuration = loader.load()

    assert configuration.secret_store is secret_store
