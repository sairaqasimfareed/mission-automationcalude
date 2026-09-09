from __future__ import annotations

from src.services.registry.voice_provider_mapping_repository import (
    InMemoryVoiceProviderMappingRepository,
)
from src.services.voice_provider_mapping_service import VoiceProviderMappingService


def _service(
    repository: InMemoryVoiceProviderMappingRepository | None = None,
) -> VoiceProviderMappingService:
    service = VoiceProviderMappingService(
        repository=repository or InMemoryVoiceProviderMappingRepository()
    )
    service.load()
    return service


def test_get_voice_id_returns_none_when_unregistered() -> None:
    service = _service()

    assert (
        service.get_voice_id(
            voice_profile_id="voice.horror_whisper", provider_name="elevenlabs"
        )
        is None
    )


def test_set_and_get_voice_id_round_trips() -> None:
    service = _service()

    service.set_voice_id(
        voice_profile_id="voice.horror_whisper",
        provider_name="elevenlabs",
        voice_id="real-voice-abc",
    )

    assert (
        service.get_voice_id(
            voice_profile_id="voice.horror_whisper", provider_name="elevenlabs"
        )
        == "real-voice-abc"
    )


def test_set_voice_id_persists_to_the_repository() -> None:
    repository = InMemoryVoiceProviderMappingRepository()
    service = _service(repository)

    service.set_voice_id(
        voice_profile_id="voice.horror_whisper",
        provider_name="elevenlabs",
        voice_id="real-voice-abc",
    )

    reloaded_service = _service(repository)

    assert (
        reloaded_service.get_voice_id(
            voice_profile_id="voice.horror_whisper", provider_name="elevenlabs"
        )
        == "real-voice-abc"
    )


def test_set_voice_id_replaces_an_existing_mapping() -> None:
    service = _service()

    service.set_voice_id(
        voice_profile_id="voice.horror_whisper",
        provider_name="elevenlabs",
        voice_id="old-voice",
    )
    service.set_voice_id(
        voice_profile_id="voice.horror_whisper",
        provider_name="elevenlabs",
        voice_id="new-voice",
    )

    assert (
        service.get_voice_id(
            voice_profile_id="voice.horror_whisper", provider_name="elevenlabs"
        )
        == "new-voice"
    )
    assert len(service.list_all()) == 1


def test_get_voice_id_is_case_insensitive() -> None:
    service = _service()

    service.set_voice_id(
        voice_profile_id="voice.horror_whisper",
        provider_name="elevenlabs",
        voice_id="real-voice-abc",
    )

    assert (
        service.get_voice_id(
            voice_profile_id="Voice.Horror_Whisper", provider_name="ElevenLabs"
        )
        == "real-voice-abc"
    )


def test_remove_returns_true_and_removes_a_registered_mapping() -> None:
    service = _service()

    service.set_voice_id(
        voice_profile_id="voice.horror_whisper",
        provider_name="elevenlabs",
        voice_id="real-voice-abc",
    )

    removed = service.remove(
        voice_profile_id="voice.horror_whisper", provider_name="elevenlabs"
    )

    assert removed is True
    assert (
        service.get_voice_id(
            voice_profile_id="voice.horror_whisper", provider_name="elevenlabs"
        )
        is None
    )


def test_remove_returns_false_when_nothing_was_registered() -> None:
    service = _service()

    removed = service.remove(
        voice_profile_id="voice.horror_whisper", provider_name="elevenlabs"
    )

    assert removed is False


def test_list_all_is_sorted_and_reflects_current_state() -> None:
    service = _service()

    service.set_voice_id(
        voice_profile_id="voice.neutral_narrator",
        provider_name="elevenlabs",
        voice_id="voice-b",
    )
    service.set_voice_id(
        voice_profile_id="voice.horror_whisper",
        provider_name="elevenlabs",
        voice_id="voice-a",
    )

    mappings = service.list_all()

    assert [mapping.voice_profile_id for mapping in mappings] == [
        "voice.horror_whisper",
        "voice.neutral_narrator",
    ]


def test_different_providers_for_the_same_profile_are_independent() -> None:
    service = _service()

    service.set_voice_id(
        voice_profile_id="voice.horror_whisper",
        provider_name="elevenlabs",
        voice_id="elevenlabs-voice",
    )
    service.set_voice_id(
        voice_profile_id="voice.horror_whisper",
        provider_name="openai",
        voice_id="openai-voice",
    )

    assert (
        service.get_voice_id(
            voice_profile_id="voice.horror_whisper", provider_name="elevenlabs"
        )
        == "elevenlabs-voice"
    )
    assert (
        service.get_voice_id(
            voice_profile_id="voice.horror_whisper", provider_name="openai"
        )
        == "openai-voice"
    )
