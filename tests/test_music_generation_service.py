from __future__ import annotations

from src.models.editing_directives import DirectiveIntensity
from src.models.resolved_editing_blueprint import (
    ResolvedMusicInstruction,
    ResolvedPresetReference,
)
from src.providers.music_provider import MusicProvider
from src.services.music_generation_service import MusicGenerationService


def _preset(
    *,
    resolved_preset_id: str = "music.horror_low_drone",
    implementation: dict[str, object] | None = None,
) -> ResolvedPresetReference:
    return ResolvedPresetReference(
        directive_path="music.preset_id",
        requested_preset_id=resolved_preset_id,
        resolved_preset_id=resolved_preset_id,
        found_exact_match=True,
        implementation=implementation or {},
    )


def _instruction(
    *,
    preset: ResolvedPresetReference | None = None,
    volume_percent: float = 25.0,
    duck_under_voice: bool = True,
) -> ResolvedMusicInstruction:
    return ResolvedMusicInstruction(
        preset=preset or _preset(),
        intensity=DirectiveIntensity.LOW,
        volume_percent=volume_percent,
        fade_in_seconds=1.0,
        fade_out_seconds=2.0,
        duck_under_voice=duck_under_voice,
        enabled=True,
    )


class FakeMusicProvider(MusicProvider):
    def __init__(
        self,
        *,
        name: str = "fake",
        output_file: str = "dry-run://music/test.mp3",
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

    def generate_music(self, *, library_query: str, duration_seconds: float) -> str:
        self.received_query = library_query

        if self._raise_on_generate is not None:
            raise self._raise_on_generate

        return self._output_file


def test_generate_returns_ready_audio_track() -> None:
    provider = FakeMusicProvider()
    service = MusicGenerationService(providers=[provider])

    result = service.generate(
        _instruction(
            preset=_preset(implementation={"library_query": "dark drone", "loop": True})
        ),
        duration_seconds=40.0,
    )

    assert result.success
    assert result.audio_track is not None
    assert result.audio_track.track_type.value == "background_music"
    assert result.audio_track.start_time_seconds == 0.0
    assert result.audio_track.duration_seconds == 40.0
    assert result.audio_track.volume == 0.25
    assert result.audio_track.loop_enabled is True
    assert result.audio_track.duck_under_voice is True
    assert provider.received_query == "dark drone"


def test_generate_falls_back_to_resolved_preset_id_when_no_library_query() -> None:
    provider = FakeMusicProvider()
    service = MusicGenerationService(providers=[provider])

    service.generate(_instruction(), duration_seconds=10.0)

    assert provider.received_query == "music.horror_low_drone"


def test_generate_rejects_non_positive_duration() -> None:
    service = MusicGenerationService(providers=[FakeMusicProvider()])

    result = service.generate(_instruction(), duration_seconds=0.0)

    assert not result.success
    assert result.failure is not None
    assert result.failure.reason == "invalid_duration"


def test_generate_fails_when_no_provider_configured() -> None:
    service = MusicGenerationService(providers=[])

    result = service.generate(_instruction(), duration_seconds=10.0)

    assert not result.success
    assert result.failure is not None
    assert result.failure.reason == "no_provider_available"


def test_generate_fails_when_requested_provider_unhealthy() -> None:
    """
    provider_name selection bypasses the health-filtered default
    lookup (which would otherwise just report no_provider_available
    for the only, unhealthy, provider) - this is the only path that
    actually reaches the provider_unhealthy failure branch.
    """

    provider = FakeMusicProvider(healthy=False)
    service = MusicGenerationService(providers=[provider])

    result = service.generate(
        _instruction(),
        duration_seconds=10.0,
        provider_name="fake",
    )

    assert not result.success
    assert result.failure is not None
    assert result.failure.reason == "provider_unhealthy"


def test_generate_fails_when_provider_raises() -> None:
    provider = FakeMusicProvider(raise_on_generate=RuntimeError("boom"))
    service = MusicGenerationService(providers=[provider])

    result = service.generate(_instruction(), duration_seconds=10.0)

    assert not result.success
    assert result.failure is not None
    assert result.failure.reason == "provider_error"


def test_generate_fails_on_empty_output_path() -> None:
    provider = FakeMusicProvider(output_file="   ")
    service = MusicGenerationService(providers=[provider])

    result = service.generate(_instruction(), duration_seconds=10.0)

    assert not result.success
    assert result.failure is not None
    assert result.failure.reason == "empty_output_path"


def test_generate_fails_on_unsupported_output_format() -> None:
    provider = FakeMusicProvider(output_file="dry-run://music/test.exe")
    service = MusicGenerationService(providers=[provider])

    result = service.generate(_instruction(), duration_seconds=10.0)

    assert not result.success
    assert result.failure is not None
    assert result.failure.reason == "unsupported_output_format"


def test_generate_honors_requested_provider_name() -> None:
    matching = FakeMusicProvider(name="matching")
    other = FakeMusicProvider(name="other")
    service = MusicGenerationService(providers=[other, matching])

    result = service.generate(
        _instruction(),
        duration_seconds=10.0,
        provider_name="matching",
    )

    assert result.success
    assert result.provider == "matching"
