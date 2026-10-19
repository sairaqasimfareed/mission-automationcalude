"""
Compact prompts (2026-10-19). A scene with its own written paragraph already says its place, light,
composition and what was asked to be shown, so repeating them as Environment / Lighting / On screen /
Composition sections stated the same thing three or four times (live, Joan arc scene 1: the gavel, the
flame and the gold chain each four times). Such a scene now keeps the identities, the timed action, the
paragraph and the lens; a scene without a paragraph keeps every section as before. Trailing full stops are
no longer doubled by the next label.
"""

from __future__ import annotations

from tests.test_scene_detail import _compile_with, _plan_for_scene_one

_DUPLICATED_SECTIONS = ("Environment:", "Lighting:", "Composition:", "On screen:")


def test_a_scene_with_its_paragraph_drops_the_sections_the_paragraph_repeats() -> None:
    text = _compile_with(_plan_for_scene_one())

    for label in _DUPLICATED_SECTIONS:
        assert label not in text, label

    for label in ("Identity:", "Scene detail:", "Lens/camera:", "Duration:"):
        assert label in text, label


def test_a_scene_without_a_paragraph_keeps_every_section() -> None:
    text = _compile_with(None)

    for label in (
        "Identity:",
        "Environment:",
        "Lighting:",
        "Composition:",
        "Lens/camera:",
    ):
        assert label in text, label
    assert "Scene detail:" not in text


def test_a_stale_paragraph_falls_back_to_the_full_sections() -> None:
    text = _compile_with(_plan_for_scene_one(hash_override="not-the-current-source"))

    assert "Environment:" in text and "Composition:" in text


def test_the_compact_prompt_is_shorter_than_the_full_one() -> None:
    assert len(_compile_with(_plan_for_scene_one())) < len(_compile_with(None)) + 400


def test_no_label_is_preceded_by_a_doubled_full_stop() -> None:
    for plan in (_plan_for_scene_one(), None):
        text = _compile_with(plan)

        assert ".." not in text.replace("...", ""), text


def test_every_sub_clip_of_a_split_scene_is_compact_too() -> None:
    for text in _compile_with(_plan_for_scene_one(), sub_clips=True):
        for label in _DUPLICATED_SECTIONS:
            assert label not in text, label
        assert "Scene detail:" in text


# ------------------------------------------------------------------ the style leads the prompt


def _compile_with_look(plan):  # type: ignore[no-untyped-def]
    from src.models.project_look import ProjectLook
    from src.services.cinematic_prompt_compilation_service import (
        CinematicPromptCompilationService,
    )
    from tests.test_cinematic_prompt_compilation_service import _bible, _scene
    from tests.test_scene_detail import _shot_plan

    look = ProjectLook(
        color_palette="cold slate and ink",
        camera_feel="ink-heavy anime linework and stark contrast",
    )
    package = CinematicPromptCompilationService().compile(
        scenes=[_scene(1)],
        shot_plan=_shot_plan(),
        visual_continuity_bible=_bible(),
        production_semantic_brief=None,
        script_lock_hash="hash123",
        scene_detail_plan=plan,
        project_look=look,
    )

    return package.prompts[0].prompt_text


def test_the_series_style_is_the_first_thing_in_a_prompt_and_not_repeated_at_the_end() -> (
    None
):
    for plan in (_plan_for_scene_one(), None):
        text = _compile_with_look(plan)

        assert text.startswith("Visual style for the whole video"), text[:80]
        assert text.count("ink-heavy anime linework") == 1
        assert "Duration:" in text and text.index("Duration:") > text.index(
            "Lens/camera:"
        )


def test_the_brief_says_a_different_palette_is_only_a_colour_grade() -> None:
    from src.services.genre_visual_mood import visual_direction

    text = visual_direction("genre.horror", "Warm sepia for flashbacks.")

    assert "colour GRADE of the same look" in text
    assert "same drawing style" in text
