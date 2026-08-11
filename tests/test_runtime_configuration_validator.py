from __future__ import annotations

from pathlib import Path

import pytest

from src.models.provider_profile import ProviderCategory, ProviderProfile
from src.models.voice_profile import VoiceProfile
from src.services.runtime_configuration_validator import (
    RuntimeConfigurationValidator,
)
from src.services.secrets.provider_secret_manager import (
    InMemorySecretStore,
    ProviderSecretManager,
)


def _neutral_narrator() -> VoiceProfile:
    return VoiceProfile(
        profile_id="voice.neutral_narrator",
        display_name="Neutral Narrator",
        fallback_profile_id=None,
    )


def test_validate_passes_for_consistent_configuration() -> None:
    secret_store = InMemorySecretStore()
    secret_manager = ProviderSecretManager(secret_store=secret_store)

    secret = secret_manager.create_secret(
        profile_id="provider.llm.openai",
        secret_value="sk-test-secret-key",
    )

    profile = ProviderProfile(
        profile_id="provider.llm.openai",
        display_name="OpenAI",
        provider_name="openai",
        category=ProviderCategory.LLM,
        enabled=True,
        secret_reference=secret.secret_reference,
    )

    RuntimeConfigurationValidator(
        secret_store=secret_store,
        provider_profiles=[profile],
        voice_profiles=[_neutral_narrator()],
    ).validate()


def test_validate_skips_provider_profile_without_secret_reference() -> None:
    secret_store = InMemorySecretStore()

    profile = ProviderProfile(
        profile_id="provider.llm.disabled",
        display_name="Disabled Provider",
        provider_name="openai",
        category=ProviderCategory.LLM,
        enabled=False,
        secret_reference=None,
    )

    RuntimeConfigurationValidator(
        secret_store=secret_store,
        provider_profiles=[profile],
        voice_profiles=[_neutral_narrator()],
    ).validate()


def test_validate_rejects_dangling_secret_reference() -> None:
    secret_store = InMemorySecretStore()

    profile = ProviderProfile(
        profile_id="provider.llm.openai",
        display_name="OpenAI",
        provider_name="openai",
        category=ProviderCategory.LLM,
        enabled=True,
        secret_reference="secret://providers/provider.llm.openai/missing",
    )

    with pytest.raises(ValueError, match="provider.llm.openai"):
        RuntimeConfigurationValidator(
            secret_store=secret_store,
            provider_profiles=[profile],
            voice_profiles=[_neutral_narrator()],
        ).validate()


def test_validate_rejects_unresolved_voice_fallback() -> None:
    secret_store = InMemorySecretStore()

    orphaned_profile = VoiceProfile(
        profile_id="voice.narrator_two",
        display_name="Narrator Two",
        fallback_profile_id="voice.does_not_exist",
    )

    with pytest.raises(ValueError, match="voice.does_not_exist"):
        RuntimeConfigurationValidator(
            secret_store=secret_store,
            provider_profiles=[],
            voice_profiles=[orphaned_profile],
        ).validate()


def test_validate_accepts_fallback_present_in_voice_profile_list() -> None:
    secret_store = InMemorySecretStore()

    secondary_profile = VoiceProfile(
        profile_id="voice.narrator_two",
        display_name="Narrator Two",
        fallback_profile_id="voice.neutral_narrator",
    )

    RuntimeConfigurationValidator(
        secret_store=secret_store,
        provider_profiles=[],
        voice_profiles=[_neutral_narrator(), secondary_profile],
    ).validate()


def test_validate_accepts_missing_checkpoint_storage_root(
    tmp_path: Path,
) -> None:
    secret_store = InMemorySecretStore()

    RuntimeConfigurationValidator(
        secret_store=secret_store,
        provider_profiles=[],
        voice_profiles=[_neutral_narrator()],
        checkpoint_storage_root=tmp_path / "does-not-exist-yet",
    ).validate()


def test_validate_accepts_existing_checkpoint_directory(
    tmp_path: Path,
) -> None:
    secret_store = InMemorySecretStore()

    checkpoint_root = tmp_path / "checkpoints"
    checkpoint_root.mkdir()

    RuntimeConfigurationValidator(
        secret_store=secret_store,
        provider_profiles=[],
        voice_profiles=[_neutral_narrator()],
        checkpoint_storage_root=checkpoint_root,
    ).validate()


def test_validate_rejects_checkpoint_storage_root_that_is_a_file(
    tmp_path: Path,
) -> None:
    secret_store = InMemorySecretStore()

    checkpoint_root = tmp_path / "checkpoints.txt"
    checkpoint_root.write_text("not a directory")

    with pytest.raises(ValueError, match="not a directory"):
        RuntimeConfigurationValidator(
            secret_store=secret_store,
            provider_profiles=[],
            voice_profiles=[_neutral_narrator()],
            checkpoint_storage_root=checkpoint_root,
        ).validate()
