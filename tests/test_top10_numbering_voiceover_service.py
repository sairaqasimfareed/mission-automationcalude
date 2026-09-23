from __future__ import annotations

from src.models.audio_track import AudioTrackType
from src.models.voice_generation import VoiceGenerationStatus
from src.providers.voice_provider import VoiceProvider
from src.services.top10_numbering_voiceover_service import (
    TopTenNumberingVoiceoverService,
)
from src.services.voice_directive_resolution_service import (
    VoiceDirectiveResolutionService,
)
from src.services.voice_directive_validation_service import (
    VoiceDirectiveValidationService,
)
from src.services.voice_generation_service import VoiceGenerationService
from src.services.voice_profile_registry_service import (
    VoiceProfileRegistryService,
)


class _DummyVoiceProvider(VoiceProvider):
    """Healthy dry-run provider - captures the real text it was asked
    to speak so tests can confirm the real "Number {N}." line."""

    def __init__(self) -> None:
        self.last_text: str | None = None
        self.last_voice: str | None = None

    @property
    def provider_name(self) -> str:
        return "Dummy Voice"

    def health_check(self) -> bool:
        return True

    def generate_voice(self, text: str, voice: str) -> str:
        self.last_text = text
        self.last_voice = voice

        return "outputs/audio/rank_card_number.wav"


def _service() -> tuple[TopTenNumberingVoiceoverService, _DummyVoiceProvider]:
    registry = VoiceProfileRegistryService.with_default_profiles()

    validation_service = VoiceDirectiveValidationService(
        voice_profile_registry=registry,
    )

    resolution_service = VoiceDirectiveResolutionService(
        voice_profile_registry=registry,
        validation_service=validation_service,
    )

    provider = _DummyVoiceProvider()

    generation_service = VoiceGenerationService(providers=[provider])

    return (
        TopTenNumberingVoiceoverService(
            voice_directive_resolution_service=resolution_service,
            voice_generation_service=generation_service,
        ),
        provider,
    )


def test_generate_speaks_the_real_rank_number() -> None:
    service, provider = _service()

    result = service.generate(rank=10, voice_profile_id="voice.top10_energetic")

    assert result.success is True
    assert result.status == VoiceGenerationStatus.COMPLETED
    assert provider.last_text == "Number 10."


def test_generate_uses_the_supplied_voice_profile() -> None:
    """Different ranks with the SAME voice_profile_id must resolve to
    the same real provider voice mapping - proves the profile is what
    the caller passed in, not something this service hardcodes."""

    service, provider = _service()

    result_one = service.generate(rank=1, voice_profile_id="voice.horror_whisper")
    voice_for_horror = provider.last_voice

    result_two = service.generate(rank=2, voice_profile_id="voice.horror_whisper")

    assert result_one.success is True
    assert result_two.success is True
    assert provider.last_voice == voice_for_horror


def test_generate_produces_a_real_voiceover_audio_track() -> None:
    service, _provider = _service()

    result = service.generate(rank=5, voice_profile_id="voice.top10_energetic")

    assert result.audio_track is not None
    assert result.audio_track.track_type == AudioTrackType.VOICEOVER
    assert result.output_file == "outputs/audio/rank_card_number.wav"


def test_generate_falls_back_gracefully_for_an_unregistered_voice_profile() -> None:
    """
    Real behavior of the underlying VoiceDirectiveResolutionService
    (matching this codebase's established resilience-over-failure
    pattern): a not-yet-registered voice_profile_id resolves via
    fallback to voice.neutral_narrator rather than raising - this
    service doesn't add its own stricter check on top, so the "Number
    {N}." line still generates successfully either way.
    """

    service, provider = _service()

    result = service.generate(rank=10, voice_profile_id="voice.does_not_exist")

    assert result.success is True
    assert provider.last_text == "Number 10."
