from __future__ import annotations

import subprocess
from pathlib import Path

from src.models.audio_track import AudioTrackStatus, AudioTrackType
from src.models.voice_directives import SceneVoiceDirectives, VoiceProviderPreferences
from src.providers.voice_provider import VoiceProvider
from src.services.voice_directive_resolution_service import (
    VoiceDirectiveResolutionService,
)
from src.services.voice_directive_validation_service import (
    VoiceDirectiveValidationService,
)
from src.services.voice_generation_service import VoiceGenerationService
from src.services.voice_profile_registry_service import VoiceProfileRegistryService

_registry = VoiceProfileRegistryService.with_default_profiles()

_validation_service = VoiceDirectiveValidationService(voice_profile_registry=_registry)

_resolution_service = VoiceDirectiveResolutionService(
    voice_profile_registry=_registry,
    validation_service=_validation_service,
)


class _DummyProvider(VoiceProvider):
    """Healthy provider returning a fixed (not necessarily real) output path."""

    @property
    def provider_name(self) -> str:
        return "Dummy Voice"

    def health_check(self) -> bool:
        return True

    def generate_voice(self, text: str, voice: str) -> str:
        assert text
        assert voice

        return "outputs/audio/generated_scene.wav"


def _blueprint(*, scene_number: int = 1, scene_duration_seconds: float = 15.0):
    directives = SceneVoiceDirectives(
        scene_number=scene_number,
        voice_profile_id="voice.horror_whisper",
        provider_preferences=VoiceProviderPreferences(
            preferred_provider="Dummy Voice",
            preferred_voice_id="dummy-horror-voice",
            preferred_output_format="wav",
        ),
    )

    return _resolution_service.resolve(
        directives,
        narration_text="The ancient doorway slowly opened into complete darkness.",
        scene_duration_seconds=scene_duration_seconds,
    )


def test_detect_duration_seconds_returns_the_real_measured_value() -> None:
    service = VoiceGenerationService(
        providers=[_DummyProvider()],
        ffprobe_runner=lambda command: "6.921\n",
    )

    measured = service._detect_duration_seconds(Path("irrelevant.wav"))

    assert measured == 6.921


def test_detect_duration_seconds_returns_none_on_ffprobe_failure() -> None:
    def _raise(command: list[str]) -> str:
        raise RuntimeError("simulated ffprobe failure")

    service = VoiceGenerationService(
        providers=[_DummyProvider()],
        ffprobe_runner=_raise,
    )

    assert service._detect_duration_seconds(Path("irrelevant.wav")) is None


def test_detect_duration_seconds_returns_none_on_timeout() -> None:
    def _raise(command: list[str]) -> str:
        raise subprocess.TimeoutExpired(cmd="ffprobe", timeout=30.0)

    service = VoiceGenerationService(
        providers=[_DummyProvider()],
        ffprobe_runner=_raise,
    )

    assert service._detect_duration_seconds(Path("irrelevant.wav")) is None


def test_detect_duration_seconds_returns_none_on_unparseable_output() -> None:
    service = VoiceGenerationService(
        providers=[_DummyProvider()],
        ffprobe_runner=lambda command: "not-a-number\n",
    )

    assert service._detect_duration_seconds(Path("irrelevant.wav")) is None


def test_generate_uses_the_real_measured_duration_when_available() -> None:
    """
    Real-world finding: the previous behavior always used the
    pre-generation ESTIMATE for the voice track's own duration, never
    the real generated file - every later scene's placement (and
    subtitle timing, which keys off the same estimate) accumulates
    that error across the whole video. This proves the fix picks the
    real measured value over the estimate whenever it's available.
    """

    blueprint = _blueprint(scene_duration_seconds=15.0)

    assert blueprint.estimated_speech_duration_seconds != 6.921

    service = VoiceGenerationService(
        providers=[_DummyProvider()],
        ffprobe_runner=lambda command: "6.921\n",
    )

    result = service.generate(blueprint, start_time_seconds=2.5)

    assert result.success is True
    assert result.audio_track is not None
    assert result.audio_track.duration_seconds == 6.921
    assert result.audio_track.metadata["measured_duration_seconds"] == 6.921
    assert not any("pre-generation estimate" in warning for warning in result.warnings)


def test_generate_falls_back_to_the_estimate_when_measurement_fails() -> None:
    """
    A measurement failure (ffprobe unavailable, unreadable file) must
    degrade gracefully to the old estimate-based behavior with a
    warning, never hard-fail voice generation over it.
    """

    blueprint = _blueprint(scene_duration_seconds=15.0)

    def _raise(command: list[str]) -> str:
        raise RuntimeError("simulated ffprobe failure")

    service = VoiceGenerationService(
        providers=[_DummyProvider()],
        ffprobe_runner=_raise,
    )

    result = service.generate(blueprint, start_time_seconds=0.0)

    assert result.success is True
    assert result.audio_track is not None
    assert (
        result.audio_track.duration_seconds
        == blueprint.estimated_speech_duration_seconds
    )
    assert result.audio_track.metadata["measured_duration_seconds"] is None
    assert any("pre-generation estimate" in warning for warning in result.warnings)


def test_generate_updates_the_blueprint_estimate_to_the_real_measured_value() -> None:
    """
    SubtitleExecutionService.build_scene_subtitles() reads
    blueprint.estimated_speech_duration_seconds directly, on this
    same blueprint object, later in the render pipeline - updating
    it in place here is what actually fixes subtitle/voiceover sync,
    not just the voice track's own placement.
    """

    blueprint = _blueprint(scene_duration_seconds=15.0)

    assert blueprint.estimated_speech_duration_seconds != 6.921

    service = VoiceGenerationService(
        providers=[_DummyProvider()],
        ffprobe_runner=lambda command: "6.921\n",
    )

    service.generate(blueprint, start_time_seconds=0.0)

    assert blueprint.estimated_speech_duration_seconds == 6.921


def test_generate_leaves_the_blueprint_estimate_alone_when_measurement_fails() -> None:
    blueprint = _blueprint(scene_duration_seconds=15.0)

    original_estimate = blueprint.estimated_speech_duration_seconds

    def _raise(command: list[str]) -> str:
        raise RuntimeError("simulated ffprobe failure")

    service = VoiceGenerationService(
        providers=[_DummyProvider()],
        ffprobe_runner=_raise,
    )

    service.generate(blueprint, start_time_seconds=0.0)

    assert blueprint.estimated_speech_duration_seconds == original_estimate


def test_generate_clamps_duration_when_real_narration_overshoots_the_scene_slot() -> (
    None
):
    """
    Real-world finding: real TTS pacing does not always match the
    pre-generation word-count estimate closely enough to fit the
    scene's own video slot (confirmed on a real render: a scene
    planned for 6s of video came back as 8.3s of real narration) -
    MasterEditPlanService's audio-vs-video duration check then
    refuses to render at all. Clamping to the scene's real available
    duration (blueprint.available_scene_duration_seconds) keeps this
    scene-local: no other scene's timing, and nothing about the
    video, ever moves - FilterGraphBuilderService's own always-on
    trim-safety atrim is what makes the clamp take real effect on the
    actual rendered audio, not just the declared metadata.
    """

    blueprint = _blueprint(scene_duration_seconds=6.0)

    assert blueprint.available_scene_duration_seconds == 6.0

    service = VoiceGenerationService(
        providers=[_DummyProvider()],
        ffprobe_runner=lambda command: "8.3\n",
    )

    result = service.generate(blueprint, start_time_seconds=0.0)

    assert result.success is True
    assert result.audio_track is not None
    assert result.audio_track.duration_seconds == 6.0
    assert blueprint.estimated_speech_duration_seconds == 6.0
    assert any(
        "ran" in warning and "longer than its" in warning for warning in result.warnings
    )


def test_generate_does_not_clamp_when_real_narration_fits_the_scene_slot() -> None:
    blueprint = _blueprint(scene_duration_seconds=15.0)

    service = VoiceGenerationService(
        providers=[_DummyProvider()],
        ffprobe_runner=lambda command: "10.0\n",
    )

    result = service.generate(blueprint, start_time_seconds=0.0)

    assert result.audio_track is not None
    assert result.audio_track.duration_seconds == 10.0
    assert blueprint.estimated_speech_duration_seconds == 10.0
    assert not any("longer than its" in warning for warning in result.warnings)


def test_generate_track_type_and_status_are_unaffected() -> None:
    blueprint = _blueprint()

    service = VoiceGenerationService(
        providers=[_DummyProvider()],
        ffprobe_runner=lambda command: "5.0\n",
    )

    result = service.generate(blueprint)

    assert result.audio_track is not None
    assert result.audio_track.track_type == AudioTrackType.VOICEOVER
    assert result.audio_track.status == AudioTrackStatus.READY
