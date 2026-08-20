from __future__ import annotations

import pytest

from src.models.scene import Scene, SceneStatus
from src.models.voice_directives import (
    VoiceDirectiveSource,
)
from src.models.voice_profile import VoiceEmotion
from src.services.genre_profile_registry_service import (
    GenreProfileRegistryService,
)
from src.services.genre_voice_directive_generation_service import (
    GenreVoiceDirectiveGenerationService,
)
from src.services.voice_profile_registry_service import (
    VoiceProfileRegistryService,
)


def _service() -> GenreVoiceDirectiveGenerationService:
    return GenreVoiceDirectiveGenerationService(
        genre_registry=(GenreProfileRegistryService.with_default_profiles()),
        voice_profile_registry=(VoiceProfileRegistryService.with_default_profiles()),
    )


def _scene(
    scene_number: int = 1,
    *,
    duration_seconds: int = 10,
) -> Scene:
    return Scene(
        scene_number=scene_number,
        title=f"Scene {scene_number}",
        narration=(f"Synthetic narration for scene " f"{scene_number}."),
        visual_prompt=(f"Synthetic visual prompt for scene " f"{scene_number}."),
        estimated_duration_seconds=duration_seconds,
        status=SceneStatus.READY,
    )


def test_exposes_injected_registries() -> None:
    genre_registry = GenreProfileRegistryService.with_default_profiles()
    voice_registry = VoiceProfileRegistryService.with_default_profiles()

    service = GenreVoiceDirectiveGenerationService(
        genre_registry=genre_registry,
        voice_profile_registry=voice_registry,
    )

    assert service.genre_registry is genre_registry
    assert service.voice_profile_registry is voice_registry


def test_generate_uses_genre_voice_profile() -> None:
    directives = _service().generate(
        scene=_scene(),
        genre_id="genre.horror",
    )

    assert directives.scene_number == 1
    assert directives.voice_profile_id == "voice.horror_whisper"
    assert directives.source == VoiceDirectiveSource.GENRE_PROFILE


def test_generate_uses_canonical_voice_profile_values() -> None:
    service = _service()

    directives = service.generate(
        scene=_scene(),
        genre_id="genre.horror",
    )

    profile = service.voice_profile_registry.get("voice.horror_whisper")

    assert directives.emotion == VoiceEmotion.SUSPENSEFUL
    assert directives.emotion == profile.emotion
    assert directives.pace == profile.pace
    assert directives.energy == profile.energy
    assert directives.pitch_style == profile.pitch_style
    assert directives.pause_style == profile.pause_style
    assert directives.emphasis_style == profile.emphasis_style
    assert directives.speed == profile.default_speed
    assert directives.pitch_adjustment == profile.default_pitch_adjustment
    assert directives.volume_gain_db == profile.default_volume_gain_db
    assert directives.stability == profile.default_stability
    assert directives.similarity_boost == profile.default_similarity_boost
    assert directives.style_strength == profile.default_style_strength
    assert directives.speaker_boost == profile.default_speaker_boost


def test_generate_preserves_language_inputs() -> None:
    directives = _service().generate(
        scene=_scene(),
        genre_id="genre.documentary",
        language="Urdu",
        language_code="ur-PK",
    )

    assert directives.language == "Urdu"
    assert directives.language_code == "ur-pk"


def test_generate_uses_default_language_inputs() -> None:
    directives = _service().generate(
        scene=_scene(),
        genre_id="genre.documentary",
    )

    assert directives.language == "English"
    assert directives.language_code == "en"


def test_generate_records_resolution_metadata() -> None:
    scene = _scene(
        scene_number=7,
        duration_seconds=14,
    )

    directives = _service().generate(
        scene=scene,
        genre_id="genre.horror",
    )

    metadata = directives.metadata

    assert metadata["requested_genre_id"] == "genre.horror"
    assert metadata["resolved_genre_id"] == "genre.horror"
    assert metadata["genre_fallback_used"] is False

    assert metadata["requested_voice_profile_id"] == "voice.horror_whisper"
    assert metadata["resolved_voice_profile_id"] == "voice.horror_whisper"
    assert metadata["voice_profile_fallback_used"] is False

    assert metadata["scene_title"] == "Scene 7"
    assert metadata["scene_duration_seconds"] == 14


def test_generate_records_genre_voice_defaults() -> None:
    service = _service()

    directives = service.generate(
        scene=_scene(),
        genre_id="genre.horror",
    )

    genre_profile = service.genre_registry.get("genre.horror")

    assert directives.metadata[
        "genre_voice_defaults"
    ] == genre_profile.voice.model_dump(
        mode="json",
    )


def test_generate_normalizes_requested_genre_metadata() -> None:
    directives = _service().generate(
        scene=_scene(),
        genre_id="  GENRE.HORROR  ",
    )

    assert directives.metadata["requested_genre_id"] == "genre.horror"
    assert directives.metadata["resolved_genre_id"] == "genre.horror"


def test_unknown_genre_uses_existing_genre_fallback() -> None:
    directives = _service().generate(
        scene=_scene(),
        genre_id="genre.does_not_exist",
    )

    assert directives.metadata["requested_genre_id"] == "genre.does_not_exist"
    assert directives.metadata["genre_fallback_used"] is True
    assert directives.warnings


def test_generate_many_returns_scene_number_order() -> None:
    directives = _service().generate_many(
        scenes=[
            _scene(3),
            _scene(1),
            _scene(2),
        ],
        genre_id="genre.documentary",
    )

    assert [directive.scene_number for directive in directives] == [1, 2, 3]


def test_generate_many_preserves_language_inputs() -> None:
    directives = _service().generate_many(
        scenes=[
            _scene(2),
            _scene(1),
        ],
        genre_id="genre.travel",
        language="Urdu",
        language_code="ur-PK",
    )

    assert len(directives) == 2

    assert all(directive.language == "Urdu" for directive in directives)
    assert all(directive.language_code == "ur-pk" for directive in directives)


def test_generate_many_empty_input_returns_empty_list() -> None:
    directives = _service().generate_many(
        scenes=[],
        genre_id="genre.horror",
    )

    assert directives == []


def test_generate_many_rejects_duplicate_scene_numbers() -> None:
    with pytest.raises(
        ValueError,
        match="Duplicate scene numbers",
    ):
        _service().generate_many(
            scenes=[
                _scene(1),
                _scene(1),
            ],
            genre_id="genre.horror",
        )
