"""
REQ-12 (top10 countdown rank cards), 2026-09-23: any scene ranked by
TopTenRankAssignmentService (Scene.list_rank set) must get a
visual.top10_rank_badge VisualEffectDirective injected, additive to
whatever the genre profile already contributes - every non-ranked
scene, including other genre.top10 scenes (the hook/intro), is
unaffected.
"""

from __future__ import annotations

from src.models.scene import Scene, SceneStatus
from src.services.genre_directive_generation_service import (
    GenreDirectiveGenerationService,
)
from src.services.genre_profile_registry_service import (
    GenreProfileRegistryService,
)


def _service() -> GenreDirectiveGenerationService:
    return GenreDirectiveGenerationService(
        genre_registry=GenreProfileRegistryService.with_default_profiles(),
    )


def _scene(*, list_rank: int | None) -> Scene:
    return Scene(
        scene_number=1,
        title="Number Ten",
        narration="Number ten on our list is a real surprise.",
        visual_prompt="A dramatic reveal shot",
        estimated_duration_seconds=6,
        status=SceneStatus.READY,
        list_rank=list_rank,
    )


def test_ranked_scene_gets_a_rank_badge_directive_injected() -> None:
    service = _service()

    directives = service.generate(
        scene=_scene(list_rank=10),
        genre_id="genre.top10",
    )

    badge_directives = [
        effect
        for effect in directives.visual_effects
        if effect.preset_id == "visual.top10_rank_badge"
    ]

    assert len(badge_directives) == 1
    assert badge_directives[0].rank_badge_text == "10"
    assert badge_directives[0].enabled is True


def test_unranked_top10_scene_gets_no_rank_badge_directive() -> None:
    service = _service()

    directives = service.generate(
        scene=_scene(list_rank=None),
        genre_id="genre.top10",
    )

    badge_directives = [
        effect
        for effect in directives.visual_effects
        if effect.preset_id == "visual.top10_rank_badge"
    ]

    assert badge_directives == []


def test_ranked_scene_keeps_the_genres_own_base_visual_effects_too() -> None:
    service = _service()

    unranked = service.generate(
        scene=_scene(list_rank=None),
        genre_id="genre.top10",
    )

    ranked = service.generate(
        scene=_scene(list_rank=1),
        genre_id="genre.top10",
    )

    # Additive, not a replacement: the ranked scene has exactly one
    # more visual effect than the same scene unranked.
    assert len(ranked.visual_effects) == len(unranked.visual_effects) + 1


def test_ranked_scene_in_a_non_top10_genre_still_gets_the_badge() -> None:
    """
    The injection is keyed on Scene.list_rank, not on genre_id - a
    deliberate, minimal condition (see genre_directive_generation_
    service.py), since list_rank is only ever set for genre.top10
    scenes by TopTenRankAssignmentService in the first place.
    """

    service = _service()

    directives = service.generate(
        scene=_scene(list_rank=5),
        genre_id="genre.horror",
    )

    badge_directives = [
        effect
        for effect in directives.visual_effects
        if effect.preset_id == "visual.top10_rank_badge"
    ]

    assert len(badge_directives) == 1
    assert badge_directives[0].rank_badge_text == "5"
