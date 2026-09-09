from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.voice_provider_mapping import VoiceProviderVoiceMapping


def test_constructs_successfully() -> None:
    mapping = VoiceProviderVoiceMapping(
        voice_profile_id="voice.horror_whisper",
        provider_name="elevenlabs",
        voice_id="real-voice-abc",
    )

    assert mapping.voice_profile_id == "voice.horror_whisper"
    assert mapping.provider_name == "elevenlabs"
    assert mapping.voice_id == "real-voice-abc"
    assert mapping.key == ("voice.horror_whisper", "elevenlabs")


def test_identifiers_are_normalized_to_lowercase() -> None:
    mapping = VoiceProviderVoiceMapping(
        voice_profile_id="Voice.Horror_Whisper",
        provider_name="ElevenLabs",
        voice_id="real-voice-abc",
    )

    assert mapping.voice_profile_id == "voice.horror_whisper"
    assert mapping.provider_name == "elevenlabs"


def test_empty_voice_profile_id_is_rejected() -> None:
    with pytest.raises(ValidationError):
        VoiceProviderVoiceMapping(
            voice_profile_id="   ", provider_name="elevenlabs", voice_id="x"
        )


def test_empty_voice_id_is_rejected() -> None:
    with pytest.raises(ValidationError):
        VoiceProviderVoiceMapping(
            voice_profile_id="voice.neutral_narrator",
            provider_name="elevenlabs",
            voice_id="   ",
        )


def test_notes_are_stripped() -> None:
    mapping = VoiceProviderVoiceMapping(
        voice_profile_id="voice.neutral_narrator",
        provider_name="elevenlabs",
        voice_id="x",
        notes="  added from My Voices  ",
    )

    assert mapping.notes == "added from My Voices"
