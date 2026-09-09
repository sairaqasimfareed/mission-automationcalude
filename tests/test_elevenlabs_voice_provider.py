from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from src.models.provider_profile import ProviderCategory, ProviderProfile
from src.models.resolved_voice_blueprint import (
    ResolvedVoiceBlueprint,
    ResolvedVoiceProfileReference,
    VoiceBlueprintResolutionStatus,
)
from src.models.voice_directives import (
    PronunciationDirective,
    VoiceDeliveryMode,
    VoiceEmotion,
    VoiceProviderPreferences,
)
from src.providers.elevenlabs_voice_provider import ElevenLabsVoiceProvider
from src.services.http.http_provider_executor import (
    HttpProviderExecutionError,
    HttpTransportResponse,
    PreparedHttpRequest,
)
from src.services.voice_pitch_shift_service import VoicePitchShiftService


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
    provider_preferences=VoiceProviderPreferences(preferred_voice_id="voice-real-123"),
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

# --- Voice gap #5 (2026-09-09 audit): a pronunciation directive
# triggers a real dictionary-creation call before the TTS call, and
# the TTS request references its locator. ---


class _RoutedTransport:
    """Returns a different response depending on the request's URL."""

    def __init__(
        self, responses_by_url_fragment: dict[str, HttpTransportResponse]
    ) -> None:
        self.responses_by_url_fragment = responses_by_url_fragment
        self.received_requests: list[PreparedHttpRequest] = []

    def __call__(self, request: PreparedHttpRequest) -> HttpTransportResponse:
        self.received_requests.append(request)

        for fragment, response in self.responses_by_url_fragment.items():
            if fragment in request.url:
                return response

        raise AssertionError(f"No fake response configured for {request.url}")


pronunciation_blueprint = ResolvedVoiceBlueprint(
    scene_number=2,
    status=VoiceBlueprintResolutionStatus.RESOLVED,
    profile=ResolvedVoiceProfileReference(
        requested_profile_id="voice.neutral_narrator",
        resolved_profile_id="voice.neutral_narrator",
        display_name="Neutral Narrator",
    ),
    narration_text="The Mary Celeste was found adrift in 1872.",
    pronunciation_directives=[
        PronunciationDirective(
            text="Celeste", pronunciation="seh-LEST", alphabet="alias"
        )
    ],
    provider_preferences=VoiceProviderPreferences(preferred_voice_id="voice-real-123"),
)

routed_transport = _RoutedTransport(
    {
        "pronunciation-dictionaries": HttpTransportResponse(
            status_code=200,
            headers={},
            content=b'{"id": "dict-123", "version_id": "ver-456"}',
        ),
        "text-to-speech": HttpTransportResponse(
            status_code=200, headers={}, content=b"pronunciation-audio"
        ),
    }
)

with TemporaryDirectory() as temp_dir:
    provider = ElevenLabsVoiceProvider(
        profile=profile,
        api_key="real-key-123",
        transport=routed_transport,
        output_directory=temp_dir,
    )

    result_path = Path(provider.generate_from_blueprint(pronunciation_blueprint))

    assert result_path.exists()
    assert result_path.read_bytes() == b"pronunciation-audio"
    assert len(routed_transport.received_requests) == 2

    dictionary_request = routed_transport.received_requests[0]
    assert "pronunciation-dictionaries/add-from-rules" in dictionary_request.url
    assert dictionary_request.json_body is not None
    assert dictionary_request.json_body["rules"][0]["string_to_replace"] == "Celeste"

    tts_request = routed_transport.received_requests[1]
    assert tts_request.json_body is not None
    locators = tts_request.json_body["pronunciation_dictionary_locators"]
    assert locators == [
        {"pronunciation_dictionary_id": "dict-123", "version_id": "ver-456"}
    ]

print("ElevenLabsVoiceProvider pronunciation-dictionary success case passed.")

# A failed dictionary-creation call must not fail voice generation
# itself - it degrades to no pronunciation_dictionary_locators.

failing_dictionary_transport = _RoutedTransport(
    {
        "pronunciation-dictionaries": HttpTransportResponse(
            status_code=500, headers={}, content=b"server error"
        ),
        "text-to-speech": HttpTransportResponse(
            status_code=200, headers={}, content=b"fallback-audio"
        ),
    }
)

with TemporaryDirectory() as temp_dir:
    provider = ElevenLabsVoiceProvider(
        profile=profile,
        api_key="real-key-123",
        transport=failing_dictionary_transport,
        output_directory=temp_dir,
    )

    fallback_path = Path(provider.generate_from_blueprint(pronunciation_blueprint))

    assert fallback_path.exists()
    assert fallback_path.read_bytes() == b"fallback-audio"

    tts_request = failing_dictionary_transport.received_requests[1]
    assert tts_request.json_body is not None
    assert "pronunciation_dictionary_locators" not in tts_request.json_body

print("ElevenLabsVoiceProvider pronunciation-dictionary failure-tolerance case passed.")

# --- Voice gap #1 (2026-09-09 audit): generate_from_blueprint() must
# never silently send an internal profile id to ElevenLabs as if it
# were a real voice_id - a blueprint with no real voice_id configured
# anywhere must raise a clear, actionable error instead. ---

no_real_voice_blueprint = ResolvedVoiceBlueprint(
    scene_number=3,
    status=VoiceBlueprintResolutionStatus.RESOLVED,
    profile=ResolvedVoiceProfileReference(
        requested_profile_id="voice.horror_whisper",
        resolved_profile_id="voice.horror_whisper",
        display_name="Horror Whisper",
    ),
    narration_text="Something moved in the dark.",
)

unreachable_transport = _RecordingTransport(
    HttpTransportResponse(status_code=200, headers={}, content=b"should-not-be-called")
)

with TemporaryDirectory() as temp_dir:
    provider = ElevenLabsVoiceProvider(
        profile=profile,
        api_key="real-key-123",
        transport=unreachable_transport,
        output_directory=temp_dir,
    )

    try:
        provider.generate_from_blueprint(no_real_voice_blueprint)
    except ValueError as error:
        assert "voice.horror_whisper" in str(error)
        assert "No real provider voice_id" in str(error)
        print("No-real-voice-id correctly raised:", error)
    else:
        raise AssertionError("Expected ValueError for a missing real voice_id.")

    # The failure must happen before any real HTTP call is made.
    assert unreachable_transport.received_requests == []

print("ElevenLabsVoiceProvider no-real-voice-id case passed.")

# --- Voice gaps #4/#9/#10 (2026-09-09 audit): real emotion-tags vs.
# real request-stitching delivery, end to end through the real
# provider call. ---

emotion_tags_blueprint = ResolvedVoiceBlueprint(
    scene_number=12,
    status=VoiceBlueprintResolutionStatus.RESOLVED,
    profile=ResolvedVoiceProfileReference(
        requested_profile_id="voice.horror_whisper",
        resolved_profile_id="voice.horror_whisper",
        display_name="Horror Whisper",
    ),
    narration_text="Something moved in the dark.",
    voice_delivery_mode=VoiceDeliveryMode.EMOTION_TAGS,
    emotion=VoiceEmotion.SUSPENSEFUL,
    provider_preferences=VoiceProviderPreferences(preferred_voice_id="voice-real-123"),
)

emotion_tags_transport = _RecordingTransport(
    HttpTransportResponse(status_code=200, headers={}, content=b"emotion-tags-audio")
)

with TemporaryDirectory() as temp_dir:
    provider = ElevenLabsVoiceProvider(
        profile=profile,
        api_key="real-key-123",
        transport=emotion_tags_transport,
        output_directory=temp_dir,
    )

    result_path = Path(provider.generate_from_blueprint(emotion_tags_blueprint))

    assert result_path.exists()
    assert result_path.read_bytes() == b"emotion-tags-audio"

    sent = emotion_tags_transport.received_requests[0]
    assert sent.json_body is not None
    assert sent.json_body["model_id"] == "eleven_v3"
    assert sent.json_body["text"] == "[worried] Something moved in the dark."
    assert "previous_text" not in sent.json_body
    assert "next_text" not in sent.json_body

print("ElevenLabsVoiceProvider emotion-tags delivery case passed.")

stitching_blueprint = ResolvedVoiceBlueprint(
    scene_number=13,
    status=VoiceBlueprintResolutionStatus.RESOLVED,
    profile=ResolvedVoiceProfileReference(
        requested_profile_id="voice.neutral_narrator",
        resolved_profile_id="voice.neutral_narrator",
        display_name="Neutral Narrator",
    ),
    narration_text="No trace of the crew was ever found.",
    voice_delivery_mode=VoiceDeliveryMode.CONTINUITY_STITCHING,
    previous_scene_narration_text="The ship was discovered adrift.",
    next_scene_narration_text="Theories about their fate still circulate today.",
    provider_preferences=VoiceProviderPreferences(preferred_voice_id="voice-real-123"),
)

stitching_transport = _RecordingTransport(
    HttpTransportResponse(status_code=200, headers={}, content=b"stitching-audio")
)

with TemporaryDirectory() as temp_dir:
    provider = ElevenLabsVoiceProvider(
        profile=profile,
        api_key="real-key-123",
        transport=stitching_transport,
        output_directory=temp_dir,
    )

    result_path = Path(provider.generate_from_blueprint(stitching_blueprint))

    assert result_path.exists()
    assert result_path.read_bytes() == b"stitching-audio"

    sent = stitching_transport.received_requests[0]
    assert sent.json_body is not None
    assert sent.json_body["model_id"] == "eleven_multilingual_v2"
    assert sent.json_body["previous_text"] == "The ship was discovered adrift."
    assert (
        sent.json_body["next_text"]
        == "Theories about their fate still circulate today."
    )

print("ElevenLabsVoiceProvider continuity-stitching delivery case passed.")

# --- Voice gap #3 (2026-09-09 audit): a real FFmpeg pitch shift runs
# after generation, on the downloaded audio file. ---

pitch_blueprint = ResolvedVoiceBlueprint(
    scene_number=14,
    status=VoiceBlueprintResolutionStatus.RESOLVED,
    profile=ResolvedVoiceProfileReference(
        requested_profile_id="voice.horror_whisper",
        resolved_profile_id="voice.horror_whisper",
        display_name="Horror Whisper",
    ),
    narration_text="Something moved in the dark.",
    pitch_adjustment=-2.0,
    provider_preferences=VoiceProviderPreferences(preferred_voice_id="voice-real-123"),
)

pitch_transport = _RecordingTransport(
    HttpTransportResponse(status_code=200, headers={}, content=b"raw-tts-audio")
)


def _ffmpeg_writing_shifted_audio(command: list[str]) -> str:
    Path(command[-1]).write_bytes(b"shifted-audio")
    return ""


with TemporaryDirectory() as temp_dir:
    shifted_service = VoicePitchShiftService(
        ffprobe_runner=lambda command: "44100",
        ffmpeg_runner=_ffmpeg_writing_shifted_audio,
    )

    provider = ElevenLabsVoiceProvider(
        profile=profile,
        api_key="real-key-123",
        transport=pitch_transport,
        output_directory=temp_dir,
        pitch_shift_service=shifted_service,
    )

    shifted_path = Path(provider.generate_from_blueprint(pitch_blueprint))

    assert shifted_path.exists()
    assert shifted_path.read_bytes() == b"shifted-audio"

print("ElevenLabsVoiceProvider real pitch-shift case passed.")

# pitch_adjustment == 0.0 must never invoke the pitch-shift service at all.

no_pitch_blueprint = ResolvedVoiceBlueprint(
    scene_number=15,
    status=VoiceBlueprintResolutionStatus.RESOLVED,
    profile=ResolvedVoiceProfileReference(
        requested_profile_id="voice.neutral_narrator",
        resolved_profile_id="voice.neutral_narrator",
        display_name="Neutral Narrator",
    ),
    narration_text="A calm, unshifted narration.",
    provider_preferences=VoiceProviderPreferences(preferred_voice_id="voice-real-123"),
)

no_pitch_transport = _RecordingTransport(
    HttpTransportResponse(status_code=200, headers={}, content=b"unshifted-audio")
)


def _pitch_shift_should_not_run(command: list[str]) -> str:
    raise AssertionError(f"Pitch shift should not run: {command}")


with TemporaryDirectory() as temp_dir:
    never_shift_service = VoicePitchShiftService(
        ffprobe_runner=_pitch_shift_should_not_run,
        ffmpeg_runner=_pitch_shift_should_not_run,
    )

    provider = ElevenLabsVoiceProvider(
        profile=profile,
        api_key="real-key-123",
        transport=no_pitch_transport,
        output_directory=temp_dir,
        pitch_shift_service=never_shift_service,
    )

    unshifted_path = Path(provider.generate_from_blueprint(no_pitch_blueprint))

    assert unshifted_path.read_bytes() == b"unshifted-audio"

print("ElevenLabsVoiceProvider zero-pitch-adjustment skip case passed.")

# A pitch-shift failure must not fail voice generation - the unshifted
# (but otherwise complete) audio is still returned.

with TemporaryDirectory() as temp_dir:

    def _failing_ffprobe(command: list[str]) -> str:
        raise RuntimeError("ffprobe exploded")

    failing_pitch_service = VoicePitchShiftService(
        ffprobe_runner=_failing_ffprobe,
        ffmpeg_runner=_pitch_shift_should_not_run,
    )

    pitch_failure_transport = _RecordingTransport(
        HttpTransportResponse(
            status_code=200, headers={}, content=b"raw-tts-audio-again"
        )
    )

    provider = ElevenLabsVoiceProvider(
        profile=profile,
        api_key="real-key-123",
        transport=pitch_failure_transport,
        output_directory=temp_dir,
        pitch_shift_service=failing_pitch_service,
    )

    fallback_path = Path(provider.generate_from_blueprint(pitch_blueprint))

    assert fallback_path.exists()
    assert fallback_path.read_bytes() == b"raw-tts-audio-again"

print("ElevenLabsVoiceProvider pitch-shift failure-tolerance case passed.")

print("ElevenLabsVoiceProvider tests completed successfully.")
