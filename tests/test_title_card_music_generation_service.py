from __future__ import annotations

from src.models.audio_track import AudioTrack, AudioTrackStatus, AudioTrackType
from src.models.music_generation import MusicGenerationResult, MusicGenerationStatus
from src.models.resolved_editing_blueprint import ResolvedMusicInstruction
from src.services.title_card_music_generation_service import (
    TitleCardMusicGenerationService,
)


def _success_result(*, output_file: str = "/tmp/sting.mp3") -> MusicGenerationResult:
    return MusicGenerationResult(
        success=True,
        status=MusicGenerationStatus.COMPLETED,
        output_file=output_file,
        audio_track=AudioTrack(
            track_type=AudioTrackType.BACKGROUND_MUSIC,
            source_file=output_file,
            duration_seconds=3.0,
            status=AudioTrackStatus.READY,
        ),
    )


class _FakeMusicGenerationService:
    def __init__(self, *, result: MusicGenerationResult) -> None:
        self._result = result
        self.calls: list[tuple[ResolvedMusicInstruction, float, str | None]] = []

    def generate(
        self,
        instruction: ResolvedMusicInstruction,
        *,
        duration_seconds: float,
        provider_name: str | None = None,
        track_duration_seconds: float | None = None,
    ) -> MusicGenerationResult:
        self.calls.append((instruction, duration_seconds, provider_name))

        return self._result


def test_generate_requests_a_one_off_custom_instruction_never_looped() -> None:
    result = _success_result()

    fake_service = _FakeMusicGenerationService(result=result)

    service = TitleCardMusicGenerationService(
        music_generation_service=fake_service,  # type: ignore[arg-type]
    )

    returned = service.generate(
        genre_music_preset_id="music.horror_low_drone",
        topic="An abandoned lighthouse.",
        duration_seconds=3.0,
    )

    assert returned is result
    assert len(fake_service.calls) == 1

    instruction, duration_seconds, provider_name = fake_service.calls[0]

    assert duration_seconds == 3.0
    assert provider_name is None
    assert instruction.preset.implementation["loop"] is False
    assert "horror low drone" in instruction.preset.implementation["library_query"]
    assert (
        "An abandoned lighthouse." in instruction.preset.implementation["library_query"]
    )


def test_generate_forwards_an_explicit_provider_name() -> None:
    result = _success_result()

    fake_service = _FakeMusicGenerationService(result=result)

    service = TitleCardMusicGenerationService(
        music_generation_service=fake_service,  # type: ignore[arg-type]
    )

    service.generate(
        genre_music_preset_id="music.travel_upbeat",
        topic="A trip to Kyoto.",
        duration_seconds=3.0,
        provider_name="elevenlabs",
    )

    _, _, provider_name = fake_service.calls[0]

    assert provider_name == "elevenlabs"


def test_readable_genre_music_character_strips_the_preset_prefix() -> None:
    fake_service = _FakeMusicGenerationService(result=_success_result())

    service = TitleCardMusicGenerationService(
        music_generation_service=fake_service,  # type: ignore[arg-type]
    )

    service.generate(
        genre_music_preset_id="music.top10_energetic_pop",
        topic="Top 10 hidden gems.",
        duration_seconds=3.0,
    )

    instruction, _, _ = fake_service.calls[0]

    assert "top10 energetic pop" in instruction.preset.implementation["library_query"]
