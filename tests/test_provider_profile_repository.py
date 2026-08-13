from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from src.models.provider_profile import ProviderCategory, ProviderProfile
from src.services.registry.provider_profile_repository import (
    InMemoryProviderProfileRepository,
    JsonProviderProfileRepository,
)

llm_profile = ProviderProfile(
    profile_id="llm-main",
    display_name="LLM Main",
    provider_name="OpenAI",
    category=ProviderCategory.LLM,
    enabled=True,
    secret_reference="secret://providers/llm-main/one",
)

voice_profile = ProviderProfile(
    profile_id="voice-main",
    display_name="Voice Main",
    provider_name="ElevenLabs",
    category=ProviderCategory.VOICE,
)


with TemporaryDirectory() as temp_dir:
    storage_path = Path(temp_dir) / "nested" / "provider_profiles.json"
    repository = JsonProviderProfileRepository(storage_path)

    assert repository.load_all() == []

    repository.save_all([llm_profile, voice_profile])

    assert storage_path.exists()

    loaded = repository.load_all()

    print("Loaded profile IDs:", [profile.profile_id for profile in loaded])

    assert [profile.profile_id for profile in loaded] == ["llm-main", "voice-main"]
    assert loaded[0].secret_reference == "secret://providers/llm-main/one"
    assert loaded[0].enabled is True
    assert loaded[1].enabled is False

    repository.save_all([voice_profile])

    assert [profile.profile_id for profile in repository.load_all()] == ["voice-main"]

    storage_path.write_text("not valid json", encoding="utf-8")

    try:
        repository.load_all()
    except RuntimeError:
        print("Corrupt storage successfully blocked.")
    else:
        raise AssertionError("Corrupt storage should raise RuntimeError.")


in_memory = InMemoryProviderProfileRepository()

assert in_memory.load_all() == []

in_memory.save_all([llm_profile])

loaded_in_memory = in_memory.load_all()

assert [profile.profile_id for profile in loaded_in_memory] == ["llm-main"]

# Mutating a returned profile must never leak back into the repository -
# save_all()/load_all() both copy, so callers can't corrupt stored state.
loaded_in_memory[0].display_name = "Mutated"

assert in_memory.load_all()[0].display_name == "LLM Main"


seeded = InMemoryProviderProfileRepository([llm_profile, voice_profile])

assert len(seeded.load_all()) == 2


print("Provider Profile Repository tests completed successfully.")
