from __future__ import annotations

from src.models.voice_provider_mapping import VoiceProviderVoiceMapping
from src.services.registry.voice_provider_mapping_repository import (
    VoiceProviderMappingRepository,
)


class VoiceProviderMappingService:
    """
    Manages real, persisted voice-profile -> provider-voice_id
    mappings.

    Voice gap #1 (2026-09-09 audit): "genre-to-voice mapping
    infrastructure." Real voice_id values cannot be hardcoded in this
    codebase's built-in VoiceProfile registry - ElevenLabs' Free tier
    blocks API access to library (non-owned) voices, so the only
    voice_ids that will ever actually work are voices the account
    owner adds to their own "My Voices," which happens incrementally
    and outside this codebase's control. This service is the real
    mechanism for registering one once it exists, with no code change
    and no redeploy - load() once at startup, call set_voice_id() as
    matching voices are added, and every resolution from then on picks
    it up automatically (see VoiceDirectiveResolutionService's
    voice_provider_mapping_service integration).
    """

    def __init__(
        self,
        *,
        repository: VoiceProviderMappingRepository,
    ) -> None:
        self._repository = repository
        self._mappings: dict[tuple[str, str], VoiceProviderVoiceMapping] = {}

    def load(self) -> None:
        """Load every persisted mapping into memory."""

        self._mappings = {
            mapping.key: mapping for mapping in self._repository.load_all()
        }

    def set_voice_id(
        self,
        *,
        voice_profile_id: str,
        provider_name: str,
        voice_id: str,
        notes: str = "",
    ) -> VoiceProviderVoiceMapping:
        """Register (or replace) the real voice_id for one profile+provider."""

        mapping = VoiceProviderVoiceMapping(
            voice_profile_id=voice_profile_id,
            provider_name=provider_name,
            voice_id=voice_id,
            notes=notes,
        )

        self._mappings[mapping.key] = mapping
        self._repository.save_all(list(self._mappings.values()))

        return mapping

    def get_voice_id(
        self,
        *,
        voice_profile_id: str,
        provider_name: str,
    ) -> str | None:
        """Return the real voice_id registered for one profile+provider, if any."""

        key = (
            voice_profile_id.strip().lower(),
            provider_name.strip().lower(),
        )

        mapping = self._mappings.get(key)

        return mapping.voice_id if mapping is not None else None

    def remove(
        self,
        *,
        voice_profile_id: str,
        provider_name: str,
    ) -> bool:
        """
        Remove a registered mapping, if present.

        Returns whether a mapping was actually removed.
        """

        key = (
            voice_profile_id.strip().lower(),
            provider_name.strip().lower(),
        )

        if key not in self._mappings:
            return False

        del self._mappings[key]
        self._repository.save_all(list(self._mappings.values()))

        return True

    def list_all(self) -> list[VoiceProviderVoiceMapping]:
        """Return every registered mapping, sorted for stable display."""

        return sorted(self._mappings.values(), key=lambda mapping: mapping.key)
