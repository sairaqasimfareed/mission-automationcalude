from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from src.models.voice_provider_mapping import VoiceProviderVoiceMapping
from src.services.registry.voice_provider_mapping_repository import (
    InMemoryVoiceProviderMappingRepository,
    JsonVoiceProviderMappingRepository,
)

horror_mapping = VoiceProviderVoiceMapping(
    voice_profile_id="voice.horror_whisper",
    provider_name="elevenlabs",
    voice_id="real-horror-voice-1",
    notes="Added from My Voices, deep/dark tone.",
)

neutral_mapping = VoiceProviderVoiceMapping(
    voice_profile_id="voice.neutral_narrator",
    provider_name="elevenlabs",
    voice_id="real-neutral-voice-1",
)

with TemporaryDirectory() as temp_dir:
    storage_path = Path(temp_dir) / "nested" / "voice_provider_mappings.json"
    repository = JsonVoiceProviderMappingRepository(storage_path)

    assert repository.load_all() == []

    repository.save_all([horror_mapping, neutral_mapping])

    assert storage_path.exists()

    loaded = repository.load_all()

    print("Loaded mapping keys:", [mapping.key for mapping in loaded])

    assert {mapping.key for mapping in loaded} == {
        ("voice.horror_whisper", "elevenlabs"),
        ("voice.neutral_narrator", "elevenlabs"),
    }

    loaded_by_key = {mapping.key: mapping for mapping in loaded}

    assert (
        loaded_by_key[("voice.horror_whisper", "elevenlabs")].voice_id
        == "real-horror-voice-1"
    )
    assert (
        loaded_by_key[("voice.horror_whisper", "elevenlabs")].notes
        == "Added from My Voices, deep/dark tone."
    )

    repository.save_all([neutral_mapping])

    assert [mapping.key for mapping in repository.load_all()] == [
        ("voice.neutral_narrator", "elevenlabs")
    ]

    storage_path.write_text("not valid json", encoding="utf-8")

    try:
        repository.load_all()
    except RuntimeError:
        print("Corrupt storage successfully blocked.")
    else:
        raise AssertionError("Corrupt storage should raise RuntimeError.")


in_memory = InMemoryVoiceProviderMappingRepository()

assert in_memory.load_all() == []

in_memory.save_all([horror_mapping])

loaded_in_memory = in_memory.load_all()

assert [mapping.key for mapping in loaded_in_memory] == [
    ("voice.horror_whisper", "elevenlabs")
]

# Mutating a returned mapping must never leak back into the repository.
loaded_in_memory[0].voice_id = "mutated"

assert in_memory.load_all()[0].voice_id == "real-horror-voice-1"


seeded = InMemoryVoiceProviderMappingRepository([horror_mapping, neutral_mapping])

assert len(seeded.load_all()) == 2


print("Voice Provider Mapping Repository tests completed successfully.")
