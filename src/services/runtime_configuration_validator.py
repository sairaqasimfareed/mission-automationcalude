from __future__ import annotations

from pathlib import Path

from src.models.provider_profile import ProviderProfile
from src.models.voice_profile import VoiceProfile
from src.services.secrets.provider_secret_manager import SecretStore


class RuntimeConfigurationValidator:
    """
    Validate a production runtime's raw configuration before any
    provider is constructed or exercised.

    This is deliberately separate from ProductionApplicationFactory
    composition and from ProviderStartupValidator's live adapter
    checks. It only inspects the raw inputs that will be handed to
    the composition root, so a broken configuration - a dangling
    secret reference, an unresolved voice-profile fallback chain, an
    unusable checkpoint path - fails fast with a clear message before
    any infrastructure is built.
    """

    def __init__(
        self,
        *,
        secret_store: SecretStore,
        provider_profiles: list[ProviderProfile],
        voice_profiles: list[VoiceProfile],
        checkpoint_storage_root: Path | None = None,
    ) -> None:
        self._secret_store = secret_store
        self._provider_profiles = provider_profiles
        self._voice_profiles = voice_profiles
        self._checkpoint_storage_root = checkpoint_storage_root

    def validate(self) -> None:
        """Raise ValueError on the first configuration problem found."""

        self._validate_provider_secrets()
        self._validate_voice_profile_fallbacks()
        self._validate_checkpoint_storage_root()

    def _validate_provider_secrets(self) -> None:
        """Reject provider profiles referencing a missing secret."""

        for profile in self._provider_profiles:
            if profile.secret_reference is None:
                continue

            if not self._secret_store.contains(profile.secret_reference):
                raise ValueError(
                    f"Provider profile '{profile.profile_id}' references "
                    "a secret that does not exist in the configured "
                    f"secret store: {profile.secret_reference}"
                )

    def _validate_voice_profile_fallbacks(self) -> None:
        """Reject voice profiles whose fallback target is missing."""

        known_profile_ids = {profile.profile_id for profile in self._voice_profiles}

        for profile in self._voice_profiles:
            fallback_id = profile.fallback_profile_id

            if fallback_id is None:
                continue

            if fallback_id not in known_profile_ids:
                raise ValueError(
                    f"Voice profile '{profile.profile_id}' declares "
                    f"fallback '{fallback_id}', which is not present in "
                    "the configured voice profile list."
                )

    def _validate_checkpoint_storage_root(self) -> None:
        """Reject a checkpoint root that exists but is not a directory."""

        root = self._checkpoint_storage_root

        if root is None:
            return

        if root.exists() and not root.is_dir():
            raise ValueError(
                f"Checkpoint storage root exists and is not a directory: {root}"
            )
