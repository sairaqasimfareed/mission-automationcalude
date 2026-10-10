"""
Lighting or an environment that refers to another scene means nothing to a clip generated on its own
(2026-10-10, live: Haunted wife). Scene 4's bible lighting read "Same warm, focused lighting as previous
scene", and the Prompts tab rightly flagged it. The compiler already dropped a LEADING "Same" from an
environment and filled an "unspecified" lighting; it now also replaces lighting that refers to another
scene with the project look's lighting (else a plain consistency line), and an environment that still
refers to another scene after the leading "Same" is dropped takes the place on screen.
"""

from __future__ import annotations

import pytest

from src.models.project_look import ProjectLook
from src.models.visual_continuity import (
    CanonicalEntityIdentity,
    CanonicalEntityType,
    VisualContinuityBible,
)
from src.services.cinematic_prompt_compilation_service import (
    CinematicPromptCompilationService,
)
from src.services.prompt_completeness_service import FindingCode, check_prompt_text
from tests.test_cinematic_prompt_compilation_service import _bible, _scene, _shot_plan


def _compile(bible: VisualContinuityBible, look: ProjectLook | None = None) -> str:
    package = CinematicPromptCompilationService().compile(
        scenes=[_scene(1)],
        shot_plan=_shot_plan(),
        visual_continuity_bible=bible,
        production_semantic_brief=None,
        script_lock_hash="hash123",
        project_look=look,
    )
    prompt = package.prompt_for_scene(1)
    assert prompt is not None

    return prompt.prompt_text


def _bible_with(lighting: str, location: str = "The deck") -> VisualContinuityBible:
    bible = _bible()
    bible.clip_entries[0].outgoing_state.lighting = lighting
    bible.clip_entries[0].outgoing_state.location = location

    return bible


@pytest.mark.parametrize(
    "lighting",
    [
        "Same warm, focused lighting as previous scene",
        "As in the previous shot, dim and warm",
        "Unchanged from before",
        "Similar to the earlier scene",
    ],
)
def test_lighting_that_refers_to_another_scene_takes_the_project_look(
    lighting: str,
) -> None:
    text = _compile(
        _bible_with(lighting), ProjectLook(lighting="Low-key shadowed light")
    )

    assert "Lighting: Low-key shadowed light." in text
    assert "previous" not in text.split("Lighting:")[1].split("Action")[0].lower()


def test_without_a_project_look_it_says_to_stay_consistent_in_plain_words() -> None:
    text = _compile(_bible_with("Same warm, focused lighting as previous scene"))

    assert "Lighting: natural light, consistent with the surrounding scenes." in text


def test_concrete_lighting_is_left_exactly_as_written() -> None:
    text = _compile(
        _bible_with("Dim golden lamp glow"), ProjectLook(lighting="Something else")
    )

    assert "Lighting: Dim golden lamp glow." in text


def test_a_word_that_merely_contains_same_is_not_treated_as_relative() -> None:
    text = _compile(_bible_with("Sameness of a flat grey overcast"))

    assert "Lighting: Sameness of a flat grey overcast." in text


def test_an_environment_that_still_refers_to_another_scene_takes_the_place_on_screen() -> (
    None
):
    bible = _bible_with("Dim", "Close-up of the papyrus, as in the previous scene")
    bible.identities.append(
        CanonicalEntityIdentity(
            entity_type=CanonicalEntityType.LOCATION,
            name="Egypt",
            canonical_description="A sun-scorched Nile-valley settlement.",
        )
    )
    entry = bible.clip_entries[0]
    entry.entity_names = ["Captain Briggs", "Egypt"]
    entry.on_screen_entity_names = ["Egypt"]

    text = _compile(bible)

    assert "Environment: Egypt." in text
    assert "previous scene" not in text.split("Environment:")[1].split("Lighting")[0]


def test_an_environment_that_refers_to_another_scene_with_no_place_is_left_for_the_check() -> (
    None
):
    text = _compile(
        _bible_with("Dim", "Close-up of the papyrus, as in the previous scene")
    )

    assert FindingCode.RELATIVE_WORDING in {f.code for f in check_prompt_text(text)}


def test_the_check_no_longer_flags_a_scene_whose_lighting_was_relative() -> None:
    text = _compile(
        _bible_with("Same warm, focused lighting as previous scene"),
        ProjectLook(lighting="Low-key shadowed light"),
    )

    assert FindingCode.RELATIVE_WORDING not in {f.code for f in check_prompt_text(text)}
