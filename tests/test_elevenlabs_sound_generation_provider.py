from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from src.models.provider_profile import ProviderCategory, ProviderProfile
from src.providers.elevenlabs_sound_generation_provider import (
    ElevenLabsMusicProvider,
    ElevenLabsSoundEffectProvider,
)
from src.services.http.http_provider_executor import (
    HttpTransportResponse,
    PreparedHttpRequest,
)


class _RecordingTransport:
    def __init__(self, response: HttpTransportResponse) -> None:
        self.response = response
        self.received_requests: list[PreparedHttpRequest] = []

    def __call__(self, request: PreparedHttpRequest) -> HttpTransportResponse:
        self.received_requests.append(request)

        return self.response


music_profile = ProviderProfile(
    profile_id="elevenlabs-music",
    display_name="ElevenLabs Music",
    provider_name="elevenlabs",
    category=ProviderCategory.MUSIC,
)

music_transport = _RecordingTransport(
    HttpTransportResponse(status_code=200, headers={}, content=b"music-bytes")
)

with TemporaryDirectory() as temp_dir:
    music_provider = ElevenLabsMusicProvider(
        profile=music_profile,
        api_key="real-key",
        transport=music_transport,
        output_directory=temp_dir,
    )

    assert music_provider.provider_name == "elevenlabs"
    assert music_provider.health_check() is True

    path = Path(
        music_provider.generate_music(
            library_query="dark suspense drone", duration_seconds=45.0
        )
    )

    assert path.exists()
    assert path.read_bytes() == b"music-bytes"

    sent = music_transport.received_requests[0]
    assert sent.url == "https://api.elevenlabs.io/v1/sound-generation"
    assert sent.json_body == {
        "text": "dark suspense drone",
        "duration_seconds": 45.0,
    }

print("ElevenLabsMusicProvider case passed.")


sfx_profile = ProviderProfile(
    profile_id="elevenlabs-sfx",
    display_name="ElevenLabs SFX",
    provider_name="elevenlabs",
    category=ProviderCategory.SOUND_EFFECTS,
)

sfx_transport = _RecordingTransport(
    HttpTransportResponse(status_code=200, headers={}, content=b"sfx-bytes")
)

with TemporaryDirectory() as temp_dir:
    sfx_provider = ElevenLabsSoundEffectProvider(
        profile=sfx_profile,
        api_key="real-key",
        transport=sfx_transport,
        output_directory=temp_dir,
    )

    path = Path(sfx_provider.generate_sound_effect(library_query="wooden door creak"))

    assert path.exists()
    assert path.read_bytes() == b"sfx-bytes"

    sent = sfx_transport.received_requests[0]
    # Sound effects have no target duration - duration_seconds must be
    # omitted from the request body entirely, not sent as None.
    assert sent.json_body == {"text": "wooden door creak"}

print("ElevenLabsSoundEffectProvider case passed.")
print("ElevenLabsSoundGenerationProvider tests completed successfully.")
