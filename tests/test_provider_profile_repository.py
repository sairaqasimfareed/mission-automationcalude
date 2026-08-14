from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from src.models.http_adapter_config import (
    HttpAdapterConfig,
    HttpMethod,
    HttpResponseMode,
)
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

custom_http_profile = ProviderProfile(
    profile_id="custom-tts",
    display_name="Custom TTS",
    provider_name="my-custom-tts",
    category=ProviderCategory.VOICE,
    http_adapter_config=HttpAdapterConfig(
        http_method=HttpMethod.POST,
        url_template="https://example.com/tts/{voice}",
        headers={"Authorization": "Bearer {api_key}"},
        json_body_template={"text": "{text}"},
        response_mode=HttpResponseMode.BINARY_FILE,
    ),
)


with TemporaryDirectory() as temp_dir:
    storage_path = Path(temp_dir) / "nested" / "provider_profiles.json"
    repository = JsonProviderProfileRepository(storage_path)

    assert repository.load_all() == []

    repository.save_all([llm_profile, voice_profile, custom_http_profile])

    assert storage_path.exists()

    loaded = repository.load_all()

    print("Loaded profile IDs:", [profile.profile_id for profile in loaded])

    assert {profile.profile_id for profile in loaded} == {
        "llm-main",
        "voice-main",
        "custom-tts",
    }

    loaded_by_id = {profile.profile_id: profile for profile in loaded}

    assert (
        loaded_by_id["llm-main"].secret_reference == "secret://providers/llm-main/one"
    )
    assert loaded_by_id["llm-main"].enabled is True
    assert loaded_by_id["voice-main"].enabled is False
    assert loaded_by_id["voice-main"].http_adapter_config is None
    assert loaded_by_id["custom-tts"].http_adapter_config is not None
    assert (
        loaded_by_id["custom-tts"].http_adapter_config.url_template
        == "https://example.com/tts/{voice}"
    )
    assert (
        loaded_by_id["custom-tts"].http_adapter_config.response_mode
        == HttpResponseMode.BINARY_FILE
    )

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
