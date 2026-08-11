from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.config.settings import Settings
from src.config.settings import settings as default_settings
from src.models.advanced_settings import AdvancedSettings
from src.models.provider_profile import ProviderCategory, ProviderProfile
from src.models.voice_profile import VoiceProfile
from src.providers.dry_run_voice_provider import DryRunVoiceProvider
from src.providers.voice_provider import VoiceProvider
from src.services.genre_profile_registry_service import (
    GenreProfileRegistryService,
)
from src.services.secrets.provider_secret_manager import (
    InMemorySecretStore,
    ProviderSecretManager,
    SecretStore,
)

_LLM_PROVIDER_SETTINGS_FIELDS: tuple[tuple[str, str], ...] = (
    ("openai", "OPENAI_API_KEY"),
    ("anthropic", "CLAUDE_API_KEY"),
    ("gemini", "GOOGLE_API_KEY"),
)


@dataclass(frozen=True, slots=True)
class RuntimeConfiguration:
    """
    Environment-derivable inputs for ProductionApplicationFactory.

    This deliberately does not include asset_workflow_service or
    genre_timeline_service. Those depend on local infrastructure -
    asset library paths, search/stock/manual-upload providers - that
    has no environment-variable-driven construction path yet, so the
    application entrypoint must still supply them explicitly.
    """

    secret_store: SecretStore
    provider_profiles: list[ProviderProfile]
    voice_profiles: list[VoiceProfile]
    voice_providers: list[VoiceProvider]
    genre_registry: GenreProfileRegistryService
    advanced_settings: AdvancedSettings
    checkpoint_storage_root: Path | None


class RuntimeConfigurationLoader:
    """
    Load ProductionApplicationFactory's environment-derivable inputs.

    Provider profiles are built from whichever LLM API keys are
    present in Settings. Voice profiles and the genre registry use
    Mission Automation's built-in defaults, since neither has any
    environment-variable-driven configuration surface yet.

    Mission Automation ships no concrete voice-provider adapter (for
    example ElevenLabs), so a real voice provider cannot be
    constructed from Settings alone. When MISSION_AUTOMATION_DRY_RUN
    is enabled this loader supplies DryRunVoiceProvider, matching the
    dry-run behavior already used for LLM calls. Outside dry-run,
    voice provider construction fails fast with an explicit error
    rather than silently reusing the dry-run adapter.

    Settings.MISSION_AUTOMATION_DRY_RUN is also the loader's single
    source of truth for AdvancedSettings.dry_run, keeping LLM-call
    dry-run behavior and pipeline-level dry-run behavior in sync.
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        secret_store: SecretStore | None = None,
    ) -> None:
        self._settings = settings if settings is not None else default_settings

        self._secret_store = (
            secret_store if secret_store is not None else InMemorySecretStore()
        )

    def load(self) -> RuntimeConfiguration:
        """Build one internally consistent runtime configuration."""

        dry_run = self._settings.MISSION_AUTOMATION_DRY_RUN

        secret_manager = ProviderSecretManager(secret_store=self._secret_store)

        return RuntimeConfiguration(
            secret_store=self._secret_store,
            provider_profiles=self._build_provider_profiles(
                secret_manager,
                dry_run=dry_run,
            ),
            voice_profiles=self._default_voice_profiles(),
            voice_providers=self._build_voice_providers(dry_run=dry_run),
            genre_registry=GenreProfileRegistryService.with_default_profiles(),
            advanced_settings=AdvancedSettings(dry_run=dry_run),
            checkpoint_storage_root=None,
        )

    def _build_provider_profiles(
        self,
        secret_manager: ProviderSecretManager,
        *,
        dry_run: bool,
    ) -> list[ProviderProfile]:
        """Build one LLM provider profile per configured API key."""

        profiles: list[ProviderProfile] = []

        for provider_name, settings_field in _LLM_PROVIDER_SETTINGS_FIELDS:
            api_key = getattr(self._settings, settings_field).strip()

            if not api_key:
                continue

            profiles.append(
                self._build_llm_profile(
                    secret_manager,
                    profile_id=f"provider.llm.{provider_name}",
                    display_name=f"{provider_name.title()} (LLM)",
                    provider_name=provider_name,
                    secret_value=api_key,
                )
            )

        if profiles:
            return profiles

        if dry_run:
            return [
                self._build_llm_profile(
                    secret_manager,
                    profile_id="provider.llm.dry_run",
                    display_name="Dry Run LLM Provider",
                    provider_name="openai",
                    secret_value="dry-run-placeholder-key",
                )
            ]

        raise ValueError(
            "No LLM provider API key is configured. Set at least one "
            "of OPENAI_API_KEY, CLAUDE_API_KEY, or GOOGLE_API_KEY, or "
            "enable MISSION_AUTOMATION_DRY_RUN."
        )

    @staticmethod
    def _build_llm_profile(
        secret_manager: ProviderSecretManager,
        *,
        profile_id: str,
        display_name: str,
        provider_name: str,
        secret_value: str,
    ) -> ProviderProfile:
        secret = secret_manager.create_secret(
            profile_id=profile_id,
            secret_value=secret_value,
        )

        return ProviderProfile(
            profile_id=profile_id,
            display_name=display_name,
            provider_name=provider_name,
            category=ProviderCategory.LLM,
            enabled=True,
            secret_reference=secret.secret_reference,
        )

    @staticmethod
    def _build_voice_providers(*, dry_run: bool) -> list[VoiceProvider]:
        if dry_run:
            return [DryRunVoiceProvider()]

        raise ValueError(
            "No production voice-provider adapter is configured. "
            "Mission Automation does not yet ship a concrete "
            "VoiceProvider implementation (for example ElevenLabs); "
            "voice generation currently requires "
            "MISSION_AUTOMATION_DRY_RUN to be enabled."
        )

    @staticmethod
    def _default_voice_profiles() -> list[VoiceProfile]:
        return [
            VoiceProfile(
                profile_id="voice.neutral_narrator",
                display_name="Neutral Narrator",
                fallback_profile_id=None,
            )
        ]
