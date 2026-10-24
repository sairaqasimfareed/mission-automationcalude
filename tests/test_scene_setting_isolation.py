"""
A scene is generated in ITS OWN place and era, not in every setting the video has (2026-10-10, live:
Haunted wife). The story is set in ancient Egypt with a present-day museum frame, so the project style
sheet names both; it is added to every prompt, and a papyrus lying on desert sand came out in a modern
museum. Two things carried the museum in: the style sheet's place-bound fields, and an Environment line
that read "Egypt (depicted through stock imagery or artifact close-up)".

A scene that has its own written paragraph now gets only the universal parts of the style sheet (colour
palette, camera feel) - the paragraph already states the place, the light and the sound - and a bracketed
production note is dropped from the environment.
"""

from __future__ import annotations

import pytest

from src.models.project_look import ProjectLook
from src.models.scene_detail import SceneDetail, SceneDetailPlan
from src.models.visual_continuity import VisualContinuityBible
from src.services.cinematic_prompt_compilation_service import (
    CinematicPromptCompilationService,
    _without_production_notes,
)
from src.services.scene_detail_source import scene_detail_source_hash
from tests.test_cinematic_prompt_compilation_service import _bible, _scene, _shot_plan

_LOOK = ProjectLook(
    setting="Ancient Egypt, with a modern frame in a present-day museum",
    architecture="Mudbrick houses; the museum interior is clean-walled with glass cases",
    climate="Arid desert heat",
    lighting="Dim golden lamp glow in Egypt, cold flat gallery light in the museum",
    color_palette="Desaturated ochres, dusty browns and deep black shadows",
    camera_feel="Slow documentary push-ins",
    sound="Low desert wind, the hush of an empty gallery at night",
)
_DETAIL = (
    "In the open desert of ancient Egypt, about 1000 BCE, pale sand drifts low across "
    "the foreground while an unrolled papyrus lies flat in the middle ground."
)


def _compile(bible: VisualContinuityBible | None = None, *, with_detail: bool) -> str:
    bible = bible or _bible()
    shot_plan = _shot_plan()
    scene = _scene(1)
    plan = None

    if with_detail:
        shot = shot_plan.shot_for_scene(1)
        source = scene_detail_source_hash(
            scene=scene, shot=shot, continuity=bible.entry_for_scene(1)
        )
        plan = SceneDetailPlan(
            details=[SceneDetail(scene_number=1, text=_DETAIL, source_hash=source)]
        )

    package = CinematicPromptCompilationService().compile(
        scenes=[scene],
        shot_plan=shot_plan,
        visual_continuity_bible=bible,
        production_semantic_brief=None,
        script_lock_hash="hash123",
        project_look=_LOOK,
        scene_detail_plan=plan,
    )
    prompt = package.prompt_for_scene(1)
    assert prompt is not None

    return prompt.prompt_text


def test_a_scene_with_its_own_paragraph_gets_only_the_universal_style() -> None:
    text = _compile(with_detail=True)

    assert _DETAIL in text
    assert "colour palette: Desaturated ochres" in text
    # The shot here is locked off, so the look's push-ins read "static framing" (2026-10-24).
    assert "camera feel: Static framing" in text
    assert "museum" not in text.split("Visual style for the whole video")[1].lower()
    for banned in ("setting:", "buildings and materials", "climate and plants"):
        assert banned not in text.split("Visual style for the whole video")[1]


def test_without_a_paragraph_the_whole_style_sheet_is_still_added() -> None:
    text = _compile(with_detail=False)

    assert "setting: Ancient Egypt" in text
    assert "buildings and materials: Mudbrick" in text
    assert "background sound: Low desert wind" in text


def test_universal_only_sentence_is_empty_when_only_place_bound_fields_are_set() -> (
    None
):
    look = ProjectLook(setting="Ancient Egypt", sound="Wind")

    assert look.as_prompt_sentence() != ""
    assert look.as_prompt_sentence(universal_only=True) == ""


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Egypt (depicted through stock imagery or artifact close-up)", "Egypt"),
        ("The deck (stock footage)", "The deck"),
        ("Close view of the papyrus (b-roll)", "Close view of the papyrus"),
        ("A farm (with livestock pens)", "A farm (with livestock pens)"),
        ("A market (crowded, noisy)", "A market (crowded, noisy)"),
        ("The deck", "The deck"),
    ],
)
def test_production_notes_in_brackets_are_dropped_from_an_environment(
    raw: str, expected: str
) -> None:
    assert _without_production_notes(raw) == expected


def test_the_environment_line_of_a_compiled_prompt_has_no_production_note() -> None:
    bible = _bible()
    bible.clip_entries[0].outgoing_state.location = (
        "Egypt (depicted through stock imagery or artifact close-up)"
    )

    text = _compile(bible, with_detail=False)

    assert "Environment: Egypt." in text
    assert "artifact" not in text
    assert "stock imagery" not in text
