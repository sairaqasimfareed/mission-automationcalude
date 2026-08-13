from __future__ import annotations

from src.models.editing_directives import DirectiveIntensity, DirectiveTimingMode
from src.models.resolved_editing_blueprint import (
    ResolvedPresetReference,
    ResolvedSoundEffectInstruction,
)
from src.providers.sound_effect_provider import SoundEffectProvider
from src.services.sound_effect_generation_service import (
    DEFAULT_CUE_DURATION_SECONDS,
    SoundEffectGenerationService,
)


def _preset(
    *,
    resolved_preset_id: str = "sfx.door_creak",
    implementation: dict[str, object] | None = None,
) -> ResolvedPresetReference:
    return ResolvedPresetReference(
        directive_path="sound_effects[0].preset_id",
        requested_preset_id=resolved_preset_id,
        resolved_preset_id=resolved_preset_id,
        found_exact_match=True,
        implementation=implementation or {},
    )


def _instruction(
    *,
    preset: ResolvedPresetReference | None = None,
    volume_percent: float = 70.0,
) -> ResolvedSoundEffectInstruction:
    return ResolvedSoundEffectInstruction(
        preset=preset or _preset(),
        timing_mode=DirectiveTimingMode.ABSOLUTE_SECONDS,
        start_offset_seconds=2.0,
        volume_percent=volume_percent,
        intensity=DirectiveIntensity.MEDIUM,
        enabled=True,
    )


class FakeSoundEffectProvider(SoundEffectProvider):
    def __init__(
        self,
        *,
        name: str = "fake",
        output_file: str = "dry-run://sfx/test.mp3",
        healthy: bool = True,
        raise_on_generate: Exception | None = None,
    ) -> None:
        self._name = name
        self._output_file = output_file
        self._healthy = healthy
        self._raise_on_generate = raise_on_generate
        self.received_query: str | None = None

    @property
    def provider_name(self) -> str:
        return self._name

    def health_check(self) -> bool:
        return self._healthy

    def generate_sound_effect(self, *, library_query: str) -> str:
        self.received_query = library_query

        if self._raise_on_generate is not None:
            raise self._raise_on_generate

        return self._output_file


def test_generate_returns_ready_audio_track() -> None:
    provider = FakeSoundEffectProvider()
    service = SoundEffectGenerationService(providers=[provider])

    result = service.generate(
        _instruction(preset=_preset(implementation={"library_query": "door creak"})),
        scene_number=3,
        start_time_seconds=12.5,
    )

    assert result.success
    assert result.scene_number == 3
    assert result.audio_track is not None
    assert result.audio_track.track_type.value == "sound_effect"
    assert result.audio_track.start_time_seconds == 12.5
    assert result.audio_track.duration_seconds == DEFAULT_CUE_DURATION_SECONDS
    assert result.audio_track.volume == 0.7
    assert provider.received_query == "door creak"


def test_generate_falls_back_to_resolved_preset_id_when_no_library_query() -> None:
    provider = FakeSoundEffectProvider()
    service = SoundEffectGenerationService(providers=[provider])

    service.generate(_instruction(), scene_number=1, start_time_seconds=0.0)

    assert provider.received_query == "sfx.door_creak"


def test_generate_rejects_negative_start_time() -> None:
    service = SoundEffectGenerationService(providers=[FakeSoundEffectProvider()])

    result = service.generate(_instruction(), scene_number=1, start_time_seconds=-1.0)

    assert not result.success
    assert result.failure is not None
    assert result.failure.reason == "invalid_start_time"


def test_generate_fails_when_no_provider_configured() -> None:
    service = SoundEffectGenerationService(providers=[])

    result = service.generate(_instruction(), scene_number=1, start_time_seconds=0.0)

    assert not result.success
    assert result.failure is not None
    assert result.failure.reason == "no_provider_available"


def test_generate_fails_when_provider_raises() -> None:
    provider = FakeSoundEffectProvider(raise_on_generate=RuntimeError("boom"))
    service = SoundEffectGenerationService(providers=[provider])

    result = service.generate(_instruction(), scene_number=1, start_time_seconds=0.0)

    assert not result.success
    assert result.failure is not None
    assert result.failure.reason == "provider_error"


def test_generate_fails_on_unsupported_output_format() -> None:
    provider = FakeSoundEffectProvider(output_file="dry-run://sfx/test.exe")
    service = SoundEffectGenerationService(providers=[provider])

    result = service.generate(_instruction(), scene_number=1, start_time_seconds=0.0)

    assert not result.success
    assert result.failure is not None
    assert result.failure.reason == "unsupported_output_format"
