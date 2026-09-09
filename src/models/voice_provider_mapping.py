from __future__ import annotations

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel


class VoiceProviderVoiceMapping(MissionBaseModel):
    """
    Maps one provider-independent voice profile to a real,
    provider-specific voice id (e.g. a real ElevenLabs voice actually
    owned by the account, added to "My Voices").

    This is the real, persisted piece voice gap #1 (2026-09-09 audit)
    was missing: none of this codebase's built-in VoiceProfile entries
    ever carry a real voice_id, only descriptive
    `recommended_voice_tags`. A hardcoded voice_id in Python source
    would also be wrong for this specific gap - ElevenLabs' Free tier
    blocks API access to library (non-owned) voices, so the only real
    voice_ids that will ever work for this account are voices added to
    its own "My Voices," which only the account owner can do. Storing
    the mapping here (not in source) is what lets a real id be
    registered the moment a matching voice is added, with no code
    change and no redeploy.
    """

    voice_profile_id: str = Field(min_length=1)
    provider_name: str = Field(min_length=1)
    voice_id: str = Field(min_length=1)
    notes: str = ""

    @field_validator("voice_profile_id", "provider_name")
    @classmethod
    def normalize_identifier(cls, value: str) -> str:
        normalized = value.strip().lower()

        if not normalized:
            raise ValueError("Voice provider mapping identifiers cannot be empty.")

        return normalized

    @field_validator("voice_id")
    @classmethod
    def clean_voice_id(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("A voice provider mapping's voice_id cannot be empty.")

        return cleaned

    @field_validator("notes")
    @classmethod
    def clean_notes(cls, value: str) -> str:
        return value.strip()

    @property
    def key(self) -> tuple[str, str]:
        """The (voice_profile_id, provider_name) identity of this mapping."""

        return (self.voice_profile_id, self.provider_name)
