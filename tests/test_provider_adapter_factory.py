from __future__ import annotations

from src.models.http_adapter_config import (
    HttpAdapterConfig,
    HttpMethod,
    HttpResponseMode,
    StockResultFieldMapping,
)
from src.models.provider_profile import (
    ProviderCategory,
    ProviderHealthStatus,
    ProviderProfile,
)
from src.providers.elevenlabs_sound_generation_provider import (
    ElevenLabsMusicProvider,
)
from src.providers.http.generic_http_music_provider import GenericHttpMusicProvider
from src.providers.http.generic_http_sound_effect_provider import (
    GenericHttpSoundEffectProvider,
)
from src.providers.http.generic_http_stock_provider import GenericHttpStockProvider
from src.providers.http.generic_http_voice_provider import GenericHttpVoiceProvider
from src.services.factory.provider_adapter_factory import ProviderAdapterFactory
from src.services.secrets.provider_secret_manager import (
    InMemorySecretStore,
    ProviderSecretManager,
)

secret_store = InMemorySecretStore()
secret_manager = ProviderSecretManager(secret_store=secret_store)
factory = ProviderAdapterFactory(secret_manager=secret_manager)

generic_secret = secret_manager.create_secret(
    profile_id="generic-voice", secret_value="real-secret-value"
)

# --- generic HTTP dispatch: usable VOICE profile with http_adapter_config ---

generic_voice_profile = ProviderProfile(
    profile_id="generic-voice",
    display_name="Generic Voice",
    provider_name="my-custom-tts",
    category=ProviderCategory.VOICE,
    enabled=True,
    health_status=ProviderHealthStatus.HEALTHY,
    secret_reference=generic_secret.secret_reference,
    http_adapter_config=HttpAdapterConfig(
        http_method=HttpMethod.POST,
        url_template="https://api.example.com/tts/{voice}",
        json_body_template={"text": "{text}"},
        response_mode=HttpResponseMode.BINARY_FILE,
    ),
)

# --- inert: usable VOICE profile with neither a coded name nor http_adapter_config ---

inert_secret = secret_manager.create_secret(
    profile_id="inert-voice", secret_value="real-secret-value"
)

inert_voice_profile = ProviderProfile(
    profile_id="inert-voice",
    display_name="Inert Voice",
    provider_name="nonexistent-vendor",
    category=ProviderCategory.VOICE,
    enabled=True,
    health_status=ProviderHealthStatus.HEALTHY,
    secret_reference=inert_secret.secret_reference,
)

# --- not usable: disabled, must be skipped silently (no warning) ---

disabled_voice_profile = ProviderProfile(
    profile_id="disabled-voice",
    display_name="Disabled Voice",
    provider_name="my-custom-tts",
    category=ProviderCategory.VOICE,
    enabled=False,
)

# --- bad secret: usable per the model, but the reference was never stored ---

bad_secret_profile = ProviderProfile(
    profile_id="bad-secret-voice",
    display_name="Bad Secret Voice",
    provider_name="my-custom-tts",
    category=ProviderCategory.VOICE,
    enabled=True,
    health_status=ProviderHealthStatus.HEALTHY,
    secret_reference="secret://providers/bad-secret-voice/never-stored",
    http_adapter_config=HttpAdapterConfig(
        url_template="https://api.example.com/tts/{voice}",
        response_mode=HttpResponseMode.BINARY_FILE,
    ),
)

# --- out of scope for this factory: LLM category, silently skipped ---

llm_secret = secret_manager.create_secret(
    profile_id="llm-profile", secret_value="real-secret-value"
)

llm_profile = ProviderProfile(
    profile_id="llm-profile",
    display_name="LLM Profile",
    provider_name="openai",
    category=ProviderCategory.LLM,
    enabled=True,
    health_status=ProviderHealthStatus.HEALTHY,
    secret_reference=llm_secret.secret_reference,
)

# --- MUSIC category, coded name ("elevenlabs") -> real coded adapter, ---
# --- takes priority even though it has no http_adapter_config at all. ---

coded_music_secret = secret_manager.create_secret(
    profile_id="coded-music-profile", secret_value="real-secret-value"
)

coded_music_profile = ProviderProfile(
    profile_id="coded-music-profile",
    display_name="Coded Music Profile",
    provider_name="elevenlabs",
    category=ProviderCategory.MUSIC,
    enabled=True,
    health_status=ProviderHealthStatus.HEALTHY,
    secret_reference=coded_music_secret.secret_reference,
)

# --- MUSIC category, unmatched name and no http_adapter_config -> inert ---

inert_music_secret = secret_manager.create_secret(
    profile_id="inert-music-profile", secret_value="real-secret-value"
)

inert_music_profile = ProviderProfile(
    profile_id="inert-music-profile",
    display_name="Inert Music Profile",
    provider_name="nonexistent-music-vendor",
    category=ProviderCategory.MUSIC,
    enabled=True,
    health_status=ProviderHealthStatus.HEALTHY,
    secret_reference=inert_music_secret.secret_reference,
)

report = factory.build(
    [
        generic_voice_profile,
        inert_voice_profile,
        disabled_voice_profile,
        bad_secret_profile,
        llm_profile,
        coded_music_profile,
        inert_music_profile,
    ]
)

assert len(report.voice_providers) == 1
assert isinstance(report.voice_providers[0], GenericHttpVoiceProvider)
assert report.voice_providers[0].provider_name == "my-custom-tts"

assert len(report.music_providers) == 1
assert isinstance(report.music_providers[0], ElevenLabsMusicProvider)

assert report.sound_effect_providers == []
assert report.stock_video_providers == []
assert report.stock_image_providers == []

# Three warnings expected: inert-voice and inert-music-profile (no adapter
# at all) plus bad-secret-voice's resolution failure. disabled/llm/
# coded-music profiles produce none.
print("Warnings:", report.warnings)
assert len(report.warnings) == 3

assert any("inert-voice" in warning for warning in report.warnings)
assert any("inert-music-profile" in warning for warning in report.warnings)
assert any("bad-secret-voice" in warning for warning in report.warnings)
assert not any("disabled-voice" in warning for warning in report.warnings)
assert not any("llm-profile" in warning for warning in report.warnings)
assert not any("coded-music-profile" in warning for warning in report.warnings)

# A bad secret must not prevent other profiles from building successfully -
# one misconfigured provider can't break the whole build() call.
assert len(report.voice_providers) == 1

# --- generic HTTP dispatch now also covers MUSIC, SOUND_EFFECTS, STOCK_VIDEO ---

generic_music_secret = secret_manager.create_secret(
    profile_id="generic-music", secret_value="real-secret-value"
)

generic_music_profile = ProviderProfile(
    profile_id="generic-music",
    display_name="Generic Music",
    provider_name="my-custom-music",
    category=ProviderCategory.MUSIC,
    enabled=True,
    health_status=ProviderHealthStatus.HEALTHY,
    secret_reference=generic_music_secret.secret_reference,
    http_adapter_config=HttpAdapterConfig(
        url_template="https://api.example.com/music",
        json_body_template={"prompt": "{library_query}"},
        response_mode=HttpResponseMode.BINARY_FILE,
    ),
)

generic_sfx_secret = secret_manager.create_secret(
    profile_id="generic-sfx", secret_value="real-secret-value"
)

generic_sfx_profile = ProviderProfile(
    profile_id="generic-sfx",
    display_name="Generic SFX",
    provider_name="my-custom-sfx",
    category=ProviderCategory.SOUND_EFFECTS,
    enabled=True,
    health_status=ProviderHealthStatus.HEALTHY,
    secret_reference=generic_sfx_secret.secret_reference,
    http_adapter_config=HttpAdapterConfig(
        url_template="https://api.example.com/sfx",
        json_body_template={"prompt": "{library_query}"},
        response_mode=HttpResponseMode.BINARY_FILE,
    ),
)

generic_stock_video_secret = secret_manager.create_secret(
    profile_id="generic-stock-video", secret_value="real-secret-value"
)

generic_stock_video_profile = ProviderProfile(
    profile_id="generic-stock-video",
    display_name="Generic Stock Video",
    provider_name="my-custom-stock",
    category=ProviderCategory.STOCK_VIDEO,
    enabled=True,
    health_status=ProviderHealthStatus.HEALTHY,
    secret_reference=generic_stock_video_secret.secret_reference,
    http_adapter_config=HttpAdapterConfig(
        http_method=HttpMethod.GET,
        url_template="https://api.example.com/search?query={query}",
        response_mode=HttpResponseMode.JSON_RESULT_LIST,
        response_list_path="results",
        response_field_mapping=StockResultFieldMapping(file_url_path="url"),
    ),
)

generic_stock_image_secret = secret_manager.create_secret(
    profile_id="generic-stock-image", secret_value="real-secret-value"
)

generic_stock_image_profile = ProviderProfile(
    profile_id="generic-stock-image",
    display_name="Generic Stock Image",
    provider_name="my-custom-stock-images",
    category=ProviderCategory.STOCK_IMAGE,
    enabled=True,
    health_status=ProviderHealthStatus.HEALTHY,
    secret_reference=generic_stock_image_secret.secret_reference,
    http_adapter_config=HttpAdapterConfig(
        http_method=HttpMethod.GET,
        url_template="https://api.example.com/images?query={query}",
        response_mode=HttpResponseMode.JSON_RESULT_LIST,
        response_list_path="results",
        response_field_mapping=StockResultFieldMapping(
            file_url_path="url", file_type="image/jpeg"
        ),
    ),
)

second_report = factory.build(
    [
        generic_music_profile,
        generic_sfx_profile,
        generic_stock_video_profile,
        generic_stock_image_profile,
    ]
)

assert second_report.warnings == []

assert len(second_report.music_providers) == 1
assert isinstance(second_report.music_providers[0], GenericHttpMusicProvider)

assert len(second_report.sound_effect_providers) == 1
assert isinstance(
    second_report.sound_effect_providers[0], GenericHttpSoundEffectProvider
)

assert len(second_report.stock_video_providers) == 1
assert isinstance(second_report.stock_video_providers[0], GenericHttpStockProvider)
assert second_report.stock_video_providers[0].provider_name == "my-custom-stock"

# STOCK_VIDEO and STOCK_IMAGE profiles must land in separate lists.
assert len(second_report.stock_image_providers) == 1
assert isinstance(second_report.stock_image_providers[0], GenericHttpStockProvider)
assert second_report.stock_image_providers[0].provider_name == "my-custom-stock-images"
assert (
    second_report.stock_video_providers[0] is not second_report.stock_image_providers[0]
)

# --- coded dispatch takes priority over a configured http_adapter_config ---
# --- when a profile matches a coded name for its category. ---

priority_secret = secret_manager.create_secret(
    profile_id="priority-voice", secret_value="real-secret-value"
)

priority_voice_profile = ProviderProfile(
    profile_id="priority-voice",
    display_name="Priority Voice",
    provider_name="elevenlabs",
    category=ProviderCategory.VOICE,
    enabled=True,
    health_status=ProviderHealthStatus.HEALTHY,
    secret_reference=priority_secret.secret_reference,
    http_adapter_config=HttpAdapterConfig(
        url_template="https://should-not-be-used.example.com/{voice}",
        response_mode=HttpResponseMode.BINARY_FILE,
    ),
)

third_report = factory.build([priority_voice_profile])

assert len(third_report.voice_providers) == 1
assert not isinstance(third_report.voice_providers[0], GenericHttpVoiceProvider)
assert third_report.voice_providers[0].provider_name == "elevenlabs"

print("ProviderAdapterFactory tests completed successfully.")
