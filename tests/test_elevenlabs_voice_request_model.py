from __future__ import annotations

import pytest

from src.models.elevenlabs_voice_request import (
    ElevenLabsVoiceRequest,
    ElevenLabsVoiceSettings,
)


def _settings(**overrides: object) -> ElevenLabsVoiceSettings:
    base: dict[str, object] = dict(
        stability=0.5,
        similarity_boost=0.75,
        style=0.0,
        use_speaker_boost=True,
        speed=1.0,
    )
    base.update(overrides)
    # **dict unpacking against a pydantic model's constructor is a
    # known mypy-plugin limitation (this session's own established
    # accepted-debt pattern) - suppressed here once rather than
    # re-litigated per field.
    return ElevenLabsVoiceSettings(**base)  # type: ignore[arg-type]


def test_settings_reject_out_of_range_stability() -> None:
    with pytest.raises(ValueError):
        _settings(stability=1.5)


def test_settings_reject_speed_outside_provider_range() -> None:
    with pytest.raises(ValueError):
        _settings(speed=2.0)


def test_request_defaults_unsupported_controls_to_empty() -> None:
    request = ElevenLabsVoiceRequest(
        text="Hello world.",
        voice_id="voice-1",
        model_id="eleven_multilingual_v2",
        voice_settings=_settings(),
    )

    assert request.unsupported_controls == []


def test_request_rejects_blank_text() -> None:
    with pytest.raises(ValueError):
        ElevenLabsVoiceRequest(
            text="",
            voice_id="voice-1",
            model_id="eleven_multilingual_v2",
            voice_settings=_settings(),
        )
