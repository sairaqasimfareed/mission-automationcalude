from __future__ import annotations

from pydantic import Field

from src.models.base import MissionBaseModel
from src.models.elevenlabs_pronunciation_dictionary import (
    ElevenLabsPronunciationDictionaryLocator,
)


class ElevenLabsVoiceSettings(MissionBaseModel):
    """
    Post-Script-Approval Production Plan, Phase 9: the subset of
    ResolvedVoiceBlueprint fields that map onto ElevenLabs' real,
    documented `voice_settings` request object - stability,
    similarity_boost, style, use_speaker_boost, and speed. Every field
    here corresponds to a genuinely documented ElevenLabs API
    parameter; nothing speculative is added just because
    ResolvedVoiceBlueprint happens to carry a same-shaped field (see
    ElevenLabsVoiceTranslationService's own docstring for which
    blueprint fields have no verified ElevenLabs equivalent and are
    reported as unsupported instead).
    """

    stability: float = Field(ge=0.0, le=1.0)
    similarity_boost: float = Field(ge=0.0, le=1.0)
    style: float = Field(ge=0.0, le=1.0)
    use_speaker_boost: bool
    speed: float = Field(ge=0.7, le=1.2)


class ElevenLabsVoiceRequest(MissionBaseModel):
    """
    Post-Script-Approval Production Plan, Phase 9: "Add an ElevenLabs
    translator mapping every supported blueprint property into
    provider settings and safe fallback for unsupported controls."

    The exact payload ElevenLabsVoiceProvider sends, plus an honest
    record of which ResolvedVoiceBlueprint properties this translation
    could not represent - never silently dropped, always named.
    """

    text: str = Field(min_length=1)
    voice_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    voice_settings: ElevenLabsVoiceSettings
    pronunciation_dictionary_locators: list[
        ElevenLabsPronunciationDictionaryLocator
    ] = Field(default_factory=list)
    unsupported_controls: list[str] = Field(default_factory=list)
