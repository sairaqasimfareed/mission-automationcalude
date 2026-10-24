"""Rule-based edits that fit the video-wide look line to ONE scene's shot (2026-10-24, after the
Salem "hand and seal" prompt carried a rule about mouths and a camera line that contradicted the
locked-off shot). Nothing stored changes; only the prompt compiled for that scene does.
"""

from __future__ import annotations

from src.models.project_look import ProjectLook
from src.models.visual_continuity import (
    CanonicalEntityIdentity,
    CanonicalEntityType,
    ClipContinuityEntry,
    VisualContinuityBible,
    VisualState,
)
from src.services.cinematic_prompt_compilation_service import (
    CinematicPromptCompilationService,
)
from src.services.prompt_tailoring import look_without_face_rules
from tests.test_cinematic_prompt_compilation_service import (
    _scene,
    _shot_plan,
)

_LOOK = (
    "Visual style for the whole video - colour palette: slate; camera feel: Patient 2D "
    "framing with close-ups of hands and wax seals. Lines stay heavy and black, and no "
    "mouth is ever shown moving."
)


# ------------------------------------------------------------------ the face rule


def test_the_mouth_rule_goes_when_no_person_is_in_the_shot_but_the_rest_stays() -> None:
    result = look_without_face_rules(_LOOK, person_on_screen=False)

    assert "mouth" not in result
    assert "Lines stay heavy and black." in result
    assert "close-ups of hands and wax seals" in result


def test_the_mouth_rule_stays_when_a_person_is_in_the_shot() -> None:
    assert look_without_face_rules(_LOOK, person_on_screen=True) == _LOOK


def test_a_look_with_no_face_words_is_untouched() -> None:
    plain = "Visual style for the whole video - colour palette: slate."

    assert look_without_face_rules(plain, person_on_screen=False) == plain
    assert look_without_face_rules("", person_on_screen=False) == ""


def test_a_whole_clause_about_lips_is_dropped_without_leaving_a_dangling_separator() -> (
    None
):
    result = look_without_face_rules(
        "camera feel: steady; no lips ever move; colour: grey.", person_on_screen=False
    )

    assert result == "camera feel: steady; colour: grey."


# ------------------------------------------------------- through the real compiler


def _bible(*, person: bool) -> VisualContinuityBible:
    identities = [
        CanonicalEntityIdentity(
            entity_type=CanonicalEntityType.LOCATION,
            name="The courtroom",
            canonical_description="A dark courtroom.",
        )
    ]
    names = ["The courtroom"]

    if person:
        identities.append(
            CanonicalEntityIdentity(
                entity_type=CanonicalEntityType.PERSON,
                name="Judge",
                canonical_description="A stern judge.",
            )
        )
        names.append("Judge")

    return VisualContinuityBible(
        script_lock_hash="hash123",
        identities=identities,
        clip_entries=[
            ClipContinuityEntry(
                scene_number=1,
                incoming_state=VisualState(),
                shot_action="A hand.",
                outgoing_state=VisualState(location="The bench", lighting="Low"),
                entity_names=names,
                on_screen_entity_names=names,
            )
        ],
    )


def _compile(person: bool) -> str:
    package = CinematicPromptCompilationService().compile(
        scenes=[_scene(1)],
        shot_plan=_shot_plan(),
        visual_continuity_bible=_bible(person=person),
        production_semantic_brief=None,
        script_lock_hash="hash123",
        project_look=ProjectLook(
            color_palette="slate",
            camera_feel="Patient framing, and no mouth is ever shown moving",
        ),
    )
    prompt = package.prompt_for_scene(1)
    assert prompt is not None

    return prompt.prompt_text


def test_a_prompt_for_a_shot_without_people_carries_no_mouth_rule() -> None:
    assert "mouth" not in _compile(person=False)


def test_a_prompt_for_a_shot_with_a_person_keeps_the_mouth_rule() -> None:
    assert "no mouth is ever shown moving" in _compile(person=True)
