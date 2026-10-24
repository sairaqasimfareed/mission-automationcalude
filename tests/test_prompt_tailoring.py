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


# ---------------------------------------------------------- the camera under a locked shot

from src.models.shot_planning import ShotMovement  # noqa: E402
from src.services.prompt_tailoring import look_with_fixed_camera  # noqa: E402


def test_a_locked_shot_replaces_the_looks_camera_movement_words() -> None:
    result = look_with_fixed_camera(
        "camera feel: Slow, deliberate push-ins on aged-paper cards, close-ups of eyes.",
        camera_is_static=True,
    )

    assert (
        result == "camera feel: A fixed camera on aged-paper cards, close-ups of eyes."
    )


def test_a_leading_with_is_kept_and_other_words_are_not_mistaken_for_movement() -> None:
    assert (
        look_with_fixed_camera(
            "Patient 2D framing with slow push-ins on drawn cards.",
            camera_is_static=True,
        )
        == "Patient 2D framing with a fixed camera on drawn cards."
    )
    plain = "camera feel: panoramic wide frames and panel lighting."
    assert look_with_fixed_camera(plain, camera_is_static=True) == plain


def test_several_movement_words_become_one_fixed_camera() -> None:
    result = look_with_fixed_camera(
        "camera feel: handheld movement, a gentle pan across the room, steady dolly "
        "shots; palette: slate.",
        camera_is_static=True,
    )

    assert result == "camera feel: a fixed camera; palette: slate."


def test_a_moving_shot_keeps_the_looks_camera_feel() -> None:
    feel = "camera feel: slow push-ins."

    assert look_with_fixed_camera(feel, camera_is_static=False) == feel


def _compile_with_movement(movement: ShotMovement) -> str:
    plan = _shot_plan()
    plan.shots[0].movement = movement
    package = CinematicPromptCompilationService().compile(
        scenes=[_scene(1)],
        shot_plan=plan,
        visual_continuity_bible=_bible(person=False),
        production_semantic_brief=None,
        script_lock_hash="hash123",
        project_look=ProjectLook(camera_feel="Slow, deliberate push-ins on cards"),
    )
    prompt = package.prompt_for_scene(1)
    assert prompt is not None

    return prompt.prompt_text


def test_the_compiled_prompt_of_a_static_shot_has_no_push_ins_but_a_pan_keeps_them() -> (
    None
):
    static = _compile_with_movement(ShotMovement.STATIC)
    panning = _compile_with_movement(ShotMovement.PAN)

    assert "push-ins" not in static and "A fixed camera on cards" in static
    assert "push-ins" in panning


# ------------------------------------------------- a place seen only in part (close / overhead)

from src.models.shot_planning import ShotAngle, ShotSize  # noqa: E402
from src.services.prompt_tailoring import short_place_description  # noqa: E402

_LONG_PLACE = (
    "A locked courtroom with dark wooden benches and a bar, set on a cold slate floor. "
    "A gold scales motif hangs above the central bench. "
    "A tall window throws a single cold shaft of light across the floor."
)


def test_a_long_place_description_is_cut_to_its_first_sentence() -> None:
    assert short_place_description(_LONG_PLACE) == (
        "A locked courtroom with dark wooden benches and a bar, set on a cold slate floor."
    )
    assert short_place_description("A tiny room.") == "A tiny room."


def test_one_very_long_sentence_is_cut_at_a_clause_not_mid_word() -> None:
    sentence = (
        "A courtroom with dark wooden benches and a bar, set on a cold slate floor, with a "
        "gold scales motif above the central bench, and a tall window with a cold shaft of "
        "light across the floor and dust turning in the beam."
    )
    result = short_place_description(sentence)

    assert len(result) <= 172
    assert result.endswith(".") and "," not in result[-3:]
    assert result.startswith("A courtroom with dark wooden benches")


def _compile_place(*, size: ShotSize, angle: ShotAngle, person: bool = False) -> str:
    plan = _shot_plan()
    plan.shots[0].shot_size = size
    plan.shots[0].shot_angle = angle
    bible = _bible(person=person)
    bible.identities[0].canonical_description = _LONG_PLACE
    package = CinematicPromptCompilationService().compile(
        scenes=[_scene(1)],
        shot_plan=plan,
        visual_continuity_bible=bible,
        production_semantic_brief=None,
        script_lock_hash="hash123",
    )
    prompt = package.prompt_for_scene(1)
    assert prompt is not None

    return prompt.prompt_text


def test_a_close_up_or_overhead_shot_carries_only_the_places_first_sentence() -> None:
    for size, angle in (
        (ShotSize.CLOSE_UP, ShotAngle.EYE_LEVEL),
        (ShotSize.EXTREME_CLOSE_UP, ShotAngle.EYE_LEVEL),
        (ShotSize.MEDIUM, ShotAngle.OVERHEAD),
    ):
        text = _compile_place(size=size, angle=angle)

        assert "dark wooden benches" in text
        assert "scales motif" not in text and "tall window" not in text


def test_a_wide_or_medium_shot_keeps_the_whole_place_description() -> None:
    text = _compile_place(size=ShotSize.WIDE, angle=ShotAngle.EYE_LEVEL)

    assert "scales motif" in text and "tall window" in text


def test_a_person_in_a_close_up_keeps_the_full_description() -> None:
    text = _compile_place(
        size=ShotSize.CLOSE_UP, angle=ShotAngle.EYE_LEVEL, person=True
    )

    assert "A stern judge." in text


# ------------------------------------------------------ "present-day" in a story set in the past

from src.models.scene_detail import SceneDetail, SceneDetailPlan  # noqa: E402
from src.services.prompt_tailoring import without_unsupported_present_day  # noqa: E402
from src.services.scene_detail_source import scene_detail_source_hash  # noqa: E402

_PARAGRAPH = (
    "In the locked present-day courtroom, a static overhead view looks down on a dark bench. "
    "A modern-day clerk is not shown."
)


def test_present_day_goes_when_the_setting_names_no_present() -> None:
    result = without_unsupported_present_day(_PARAGRAPH, "Salem, 1692, in a courtroom")

    assert result.startswith("In the locked courtroom, a static overhead view")
    assert "present-day" not in result and "modern-day" not in result


def test_present_day_stays_when_the_setting_names_a_present_day_frame() -> None:
    for setting in (
        "Salem, 1692, told from a present-day museum",
        "Ancient Egypt framed by a modern archive",
        "London, 2024, and 1666",
    ):
        assert without_unsupported_present_day(_PARAGRAPH, setting) == _PARAGRAPH


def test_an_empty_setting_changes_nothing_and_representative_is_not_a_present() -> None:
    assert without_unsupported_present_day(_PARAGRAPH, "") == _PARAGRAPH
    assert without_unsupported_present_day(
        _PARAGRAPH, "A representative town, 1692"
    ) != (_PARAGRAPH)


def test_the_compiled_prompt_of_a_scene_in_1692_has_no_present_day() -> None:
    scene = _scene(1)
    plan = _shot_plan()
    bible = _bible(person=False)
    shot = plan.shot_for_scene(1)
    entry = bible.entry_for_scene(1)
    detail_plan = SceneDetailPlan(
        details=[
            SceneDetail(
                scene_number=1,
                text=_PARAGRAPH,
                source_hash=scene_detail_source_hash(
                    scene=scene, shot=shot, continuity=entry
                ),
            )
        ]
    )

    package = CinematicPromptCompilationService().compile(
        scenes=[scene],
        shot_plan=plan,
        visual_continuity_bible=bible,
        production_semantic_brief=None,
        script_lock_hash="hash123",
        project_look=ProjectLook(setting="Salem, 1692"),
        scene_detail_plan=detail_plan,
    )
    prompt = package.prompt_for_scene(1)
    assert prompt is not None

    assert "In the locked courtroom" in prompt.prompt_text
    assert "present-day" not in prompt.prompt_text


def test_a_modifier_before_the_movement_goes_with_it_and_a_style_word_alone_stays() -> (
    None
):
    assert (
        look_with_fixed_camera(
            "camera feel: Slow documentary push-ins", camera_is_static=True
        )
        == "camera feel: A fixed camera"
    )
    style = "camera feel: handheld documentary realism."
    assert look_with_fixed_camera(style, camera_is_static=True) == style
