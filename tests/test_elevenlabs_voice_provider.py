from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from src.models.provider_profile import ProviderCategory, ProviderProfile
from src.models.resolved_voice_blueprint import (
    ResolvedVoiceBlueprint,
    ResolvedVoiceProfileReference,
    VoiceBlueprintResolutionStatus,
)
from src.providers.elevenlabs_voice_provider import ElevenLabsVoiceProvider
from src.services.http.http_provider_executor import (
    HttpProviderExecutionError,
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


profile = ProviderProfile(
    profile_id="elevenlabs-voice",
    display_name="ElevenLabs Voice",
    provider_name="elevenlabs",
    category=ProviderCategory.VOICE,
)

transport = _RecordingTransport(
    HttpTransportResponse(
        status_code=200, headers={}, content=b"elevenlabs-audio-bytes"
    )
)

with TemporaryDirectory() as temp_dir:
    provider = ElevenLabsVoiceProvider(
        profile=profile,
        api_key="real-key-123",
        transport=transport,
        output_directory=temp_dir,
    )

    assert provider.provider_name == "elevenlabs"
    assert provider.health_check() is True

    path = Path(provider.generate_voice("Hello from the narrator.", "voice-id-42"))

    assert path.exists()
    assert path.read_bytes() == b"elevenlabs-audio-bytes"

    sent = transport.received_requests[0]
    assert sent.method == "POST"
    assert sent.url == "https://api.elevenlabs.io/v1/text-to-speech/voice-id-42"
    assert sent.headers["xi-api-key"] == "real-key-123"
    assert sent.json_body is not None
    assert sent.json_body["text"] == "Hello from the narrator."

print("ElevenLabsVoiceProvider success case passed.")

# HTTP error status must raise, not silently write an empty/garbage file.
error_transport = _RecordingTransport(
    HttpTransportResponse(status_code=401, headers={}, content=b"unauthorized")
)

with TemporaryDirectory() as temp_dir:
    provider = ElevenLabsVoiceProvider(
        profile=profile,
        api_key="bad-key",
        transport=error_transport,
        output_directory=temp_dir,
    )

    try:
        provider.generate_voice("text", "voice-id")
    except HttpProviderExecutionError as error:
        print("HTTP 401 correctly raised:", error)
    else:
        raise AssertionError("Expected HttpProviderExecutionError.")

# A custom base_url on the profile must override the default.
custom_base_profile = ProviderProfile(
    profile_id="elevenlabs-voice-custom",
    display_name="ElevenLabs Voice (custom base)",
    provider_name="elevenlabs",
    category=ProviderCategory.VOICE,
    base_url="https://proxy.example.com/elevenlabs",
)

custom_transport = _RecordingTransport(
    HttpTransportResponse(status_code=200, headers={}, content=b"bytes")
)

with TemporaryDirectory() as temp_dir:
    provider = ElevenLabsVoiceProvider(
        profile=custom_base_profile,
        api_key="k",
        transport=custom_transport,
        output_directory=temp_dir,
    )

    provider.generate_voice("text", "voice-id")

    assert (
        custom_transport.received_requests[0].url
        == "https://proxy.example.com/elevenlabs/v1/text-to-speech/voice-id"
    )

# --- Post-Script-Approval Production Plan, Phase 9:
# generate_from_blueprint() sends the rich, translated voice_settings
# payload rather than only text/voice. ---

blueprint = ResolvedVoiceBlueprint(
    scene_number=1,
    status=VoiceBlueprintResolutionStatus.RESOLVED,
    profile=ResolvedVoiceProfileReference(
        requested_profile_id="voice.neutral_narrator",
        resolved_profile_id="voice.neutral_narrator",
        display_name="Neutral Narrator",
    ),
    narration_text="The Mary Celeste was found adrift in 1872.",
    stability=0.6,
    similarity_boost=0.8,
    style_strength=0.3,
    speaker_boost=False,
)

blueprint_transport = _RecordingTransport(
    HttpTransportResponse(status_code=200, headers={}, content=b"blueprint-audio")
)

with TemporaryDirectory() as temp_dir:
    provider = ElevenLabsVoiceProvider(
        profile=profile,
        api_key="real-key-123",
        transport=blueprint_transport,
        output_directory=temp_dir,
    )

    blueprint_path = Path(provider.generate_from_blueprint(blueprint))

    assert blueprint_path.exists()
    assert blueprint_path.read_bytes() == b"blueprint-audio"

    sent = blueprint_transport.received_requests[0]
    assert sent.json_body is not None
    assert sent.json_body["text"] == blueprint.narration_text
    voice_settings = sent.json_body["voice_settings"]
    assert voice_settings["stability"] == 0.6
    assert voice_settings["similarity_boost"] == 0.8
    assert voice_settings["style"] == 0.3
    assert voice_settings["use_speaker_boost"] is False

print("ElevenLabsVoiceProvider generate_from_blueprint case passed.")

print("ElevenLabsVoiceProvider tests completed successfully.")
