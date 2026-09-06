from __future__ import annotations

from src.models.resolved_voice_blueprint import (
    ResolvedVoiceBlueprint,
    ResolvedVoiceProfileReference,
    VoiceBlueprintResolutionStatus,
)
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


def test_generate_from_blueprint_falls_back_to_generate_voice() -> None:
    """
    Post-Script-Approval Production Plan, Phase 9: DryRunVoiceProvider
    never overrides generate_from_blueprint() - it must keep working
    unchanged via VoiceProvider's own default implementation, which
    resolves a voice ID from the blueprint and calls generate_voice()
    exactly as every caller already expected before this phase.
    """

    provider = DryRunVoiceProvider()
    blueprint = ResolvedVoiceBlueprint(
        scene_number=1,
        status=VoiceBlueprintResolutionStatus.RESOLVED,
        profile=ResolvedVoiceProfileReference(
            requested_profile_id="voice.neutral_narrator",
            resolved_profile_id="voice.neutral_narrator",
            display_name="Neutral Narrator",
        ),
        narration_text="Hello from the blueprint.",
    )

    output_file = provider.generate_from_blueprint(blueprint)

    assert output_file == "dry-run://voice/voice.neutral_narrator.mp3"
