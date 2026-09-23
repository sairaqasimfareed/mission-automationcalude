"""
REQ-1/2 (tension-adaptive film grain/vignette), 2026-09-22: real,
end-to-end verification against the actual registered genre profiles -
Scene.tension_level linearly scales within a genre's own real min/max
range into VisualEffectDirective.numeric_intensity_percent, for the
grain/vignette presets specifically (every other preset stays
untouched - None).
"""

from __future__ import annotations

from src.models.editing_directives import SceneEditingDirectives
from src.models.media_strategy import SceneSourceStatus, SceneSourceType
from src.models.scene import Scene
from src.services.genre_directive_generation_service import (
    GenreDirectiveGenerationService,
)
from src.services.genre_profile_registry_service import (
    GenreProfileRegistryService,
)


def _scene(*, tension_level: int | None) -> Scene:
    return Scene(
        scene_number=1,
        title="Test Scene",
        narration="Some narration.",
        visual_prompt="A cinematic visual.",
        estimated_duration_seconds=8,
        tension_level=tension_level,
        source_type=SceneSourceType.MANUAL_UPLOAD,
        source_status=SceneSourceStatus.READY,
        manual_file_path="assets/videos/manual/test_scene.mp4",
    )


def _service() -> GenreDirectiveGenerationService:
    return GenreDirectiveGenerationService(
        genre_registry=GenreProfileRegistryService.with_default_profiles()
    )


def _numeric_intensity(
    directives: SceneEditingDirectives, preset_id: str
) -> int | None:
    matches = [
        effect.numeric_intensity_percent
        for effect in directives.visual_effects
        if effect.preset_id == preset_id
    ]

    assert matches, f"{preset_id} not found in directives.visual_effects"

    return matches[0]


def test_horrors_calm_scene_resolves_near_its_genre_minimum() -> None:
    service = _service()

    directives = service.generate(
        scene=_scene(tension_level=0), genre_id="genre.horror"
    )

    grain = _numeric_intensity(directives, "visual.film_grain_light")
    vignette = _numeric_intensity(directives, "visual.vignette_soft")

    assert grain == 10  # horror's own film_grain_minimum_intensity_percent
    assert vignette == 20  # horror's own vignette_minimum_intensity_percent


def test_horrors_climactic_scene_resolves_near_its_genre_maximum() -> None:
    service = _service()

    directives = service.generate(
        scene=_scene(tension_level=100), genre_id="genre.horror"
    )

    grain = _numeric_intensity(directives, "visual.film_grain_light")
    vignette = _numeric_intensity(directives, "visual.vignette_soft")

    assert grain == 60  # horror's own film_grain_maximum_intensity_percent
    assert vignette == 70  # horror's own vignette_maximum_intensity_percent


def test_horrors_midpoint_scene_resolves_midway_through_the_range() -> None:
    service = _service()

    directives = service.generate(
        scene=_scene(tension_level=50), genre_id="genre.horror"
    )

    grain = _numeric_intensity(directives, "visual.film_grain_light")

    # (10 + 60) / 2 = 35
    assert grain == 35


def test_a_scene_with_no_tension_level_resolves_at_the_neutral_default() -> None:
    """The legacy sentence-split planner never sets tension_level -
    must resolve at the documented neutral midpoint (50%), not crash
    or silently default to either extreme."""

    service = _service()

    directives = service.generate(
        scene=_scene(tension_level=None), genre_id="genre.horror"
    )

    grain = _numeric_intensity(directives, "visual.film_grain_light")

    assert grain == 35  # same as the explicit tension_level=50 case


def test_travel_never_requests_grain_or_vignette_at_all() -> None:
    """The 'effectively off' bucket - travel's own visual_preset_ids
    never includes these presets in the first place, so nothing in
    directives.visual_effects should reference them regardless of
    tension_level."""

    service = _service()

    directives = service.generate(
        scene=_scene(tension_level=100), genre_id="genre.travel"
    )

    preset_ids = {effect.preset_id for effect in directives.visual_effects}

    assert "visual.film_grain_light" not in preset_ids
    assert "visual.vignette_soft" not in preset_ids


def test_every_non_grain_vignette_effect_keeps_numeric_intensity_none() -> None:
    """Confirms this change is scoped to grain/vignette only - every
    other visual effect a genre requests must still resolve to
    numeric_intensity_percent=None."""

    service = _service()

    directives = service.generate(
        scene=_scene(tension_level=80), genre_id="genre.history"
    )

    for effect in directives.visual_effects:
        if effect.preset_id in {"visual.film_grain_light", "visual.vignette_soft"}:
            assert effect.numeric_intensity_percent is not None
        else:
            assert effect.numeric_intensity_percent is None
