from __future__ import annotations

from src.providers.dry_run_voice_provider import DryRunVoiceProvider


def test_provider_name_is_dry_run() -> None:
    provider = DryRunVoiceProvider()

    assert provider.provider_name == "dry_run"


def test_health_check_always_succeeds() -> None:
    provider = DryRunVoiceProvider()

    assert provider.health_check() is True


def test_generate_voice_returns_supported_audio_format() -> None:
    provider = DryRunVoiceProvider()

    output_file = provider.generate_voice(
        text="Hello there.",
        voice="voice.neutral_narrator",
    )

    assert output_file == "dry-run://voice/voice.neutral_narrator.mp3"


def test_generate_voice_output_reflects_requested_voice() -> None:
    provider = DryRunVoiceProvider()

    first = provider.generate_voice(text="A", voice="voice.alpha")
    second = provider.generate_voice(text="B", voice="voice.beta")

    assert first != second
    assert "voice.alpha" in first
    assert "voice.beta" in second
