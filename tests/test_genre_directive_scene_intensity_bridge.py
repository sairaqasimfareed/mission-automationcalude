from __future__ import annotations

from src.models.editing_directives import DirectiveIntensity
from src.models.genre_profile import GenreEditingProfile, GenreProfile
from src.models.scene import Scene, SceneStatus
from src.services.genre_directive_generation_service import (
    GenreDirectiveGenerationService,
)
from src.services.genre_profile_registry_service import GenreProfileRegistryService


def _profile(effect_intensity: DirectiveIntensity) -> GenreProfile:
    return GenreProfile(
        genre_id="genre.test_intensity",
        display_name="Test Intensity Genre",
        editing=GenreEditingProfile(effect_intensity=effect_intensity),
    )


def _scene(narrative_function: str | None) -> Scene:
    return Scene(
        scene_number=1,
        title="Test scene",
        narration="Something happens.",
        visual_prompt="A visual.",
        estimated_duration_seconds=8,
        narrative_function=narrative_function,
        status=SceneStatus.READY,
    )


def _service() -> GenreDirectiveGenerationService:
    registry = GenreProfileRegistryService()
    registry.register(_profile(DirectiveIntensity.MEDIUM))

    return GenreDirectiveGenerationService(genre_registry=registry)


def test_scene_with_no_narrative_function_uses_the_genre_base_intensity() -> None:
    service = _service()

    directives = service.generate(
        scene=_scene(narrative_function=None),
        genre_id="genre.test_intensity",
    )

    assert directives.camera.intensity == DirectiveIntensity.MEDIUM


def test_climax_scene_steps_intensity_up_from_the_genre_base() -> None:
    service = _service()

    directives = service.generate(
        scene=_scene(narrative_function="climax"),
        genre_id="genre.test_intensity",
    )

    assert directives.camera.intensity == DirectiveIntensity.HIGH


def test_aftershock_scene_steps_intensity_down_from_the_genre_base() -> None:
    service = _service()

    directives = service.generate(
        scene=_scene(narrative_function="aftershock"),
        genre_id="genre.test_intensity",
    )

    assert directives.camera.intensity == DirectiveIntensity.LOW


def test_setup_scene_also_steps_intensity_down() -> None:
    service = _service()

    directives = service.generate(
        scene=_scene(narrative_function="setup"),
        genre_id="genre.test_intensity",
    )

    assert directives.camera.intensity == DirectiveIntensity.LOW


def test_neutral_beat_leaves_intensity_unchanged() -> None:
    service = _service()

    directives = service.generate(
        scene=_scene(narrative_function="reveal"),
        genre_id="genre.test_intensity",
    )

    assert directives.camera.intensity == DirectiveIntensity.MEDIUM


def test_intensity_does_not_exceed_the_top_of_the_scale() -> None:
    registry = GenreProfileRegistryService()
    registry.register(_profile(DirectiveIntensity.HIGH))
    service = GenreDirectiveGenerationService(genre_registry=registry)

    directives = service.generate(
        scene=_scene(narrative_function="climax"),
        genre_id="genre.test_intensity",
    )

    assert directives.camera.intensity == DirectiveIntensity.HIGH


def test_intensity_does_not_go_below_the_bottom_of_the_scale() -> None:
    registry = GenreProfileRegistryService()
    registry.register(_profile(DirectiveIntensity.VERY_LOW))
    service = GenreDirectiveGenerationService(genre_registry=registry)

    directives = service.generate(
        scene=_scene(narrative_function="aftershock"),
        genre_id="genre.test_intensity",
    )

    assert directives.camera.intensity == DirectiveIntensity.VERY_LOW


def test_visual_effects_and_animations_also_use_the_shifted_intensity() -> None:
    registry = GenreProfileRegistryService()
    registry.register(
        GenreProfile(
            genre_id="genre.test_intensity",
            display_name="Test Intensity Genre",
            editing=GenreEditingProfile(
                effect_intensity=DirectiveIntensity.MEDIUM,
                visual_preset_ids=["visual.grain"],
                animation_preset_ids=["animation.fade_in"],
            ),
        )
    )
    service = GenreDirectiveGenerationService(genre_registry=registry)

    directives = service.generate(
        scene=_scene(narrative_function="climax"),
        genre_id="genre.test_intensity",
    )

    assert directives.visual_effects[0].intensity == DirectiveIntensity.HIGH
    assert directives.animations[0].intensity == DirectiveIntensity.HIGH
