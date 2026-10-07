"""
Graphic scenes (2026-10-07).

Live (Remedy scene 13): the plan asked for an infographic. Muse drew a flat cartoon
card in the middle of photographic kitchen scenes, wrote a sentence the narration
never said, and the prompt contradicted itself ("no on-screen text" next to a text
overlay). Two fixes: a graphic scene's prompt names the only words allowed on screen,
and the operator can switch the scene to live footage in the project's main setting.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import MagicMock  # noqa: E402

from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel  # noqa: E402

from src.models.project_look import ProjectLook  # noqa: E402
from src.models.scene import Scene  # noqa: E402
from src.models.shot_planning import (  # noqa: E402
    CinematicShotPlan,
    ShotAngle,
    ShotMovement,
    ShotSize,
    ShotSpecification,
)
from src.models.visual_continuity import (  # noqa: E402
    CanonicalEntityIdentity,
    CanonicalEntityType,
    ClipContinuityEntry,
    VisualContinuityBible,
    VisualState,
)
from src.services.cinematic_prompt_compilation_service import (  # noqa: E402
    CinematicPromptCompilationService,
)
from src.services.scene_visual_treatment import (  # noqa: E402
    effective_on_screen_names,
    exact_text_for,
    is_graphic_scene,
    main_place,
    renders_as_graphic,
)
from tests.test_clip_workspace_view_scene_generation import (  # noqa: E402
    _build_view,
    _FakeSceneVideoGenerationService,
    _job,
)
from tests.test_clip_workspace_view_scene_generation import (  # noqa: E402
    qapp as qapp,  # noqa: PLC0414 - fixture
)

_STANDARD = "no on-screen text, logos, or watermarks"


def _scene(number: int, narration: str = "Evidence in adults is limited.") -> Scene:
    return Scene(
        scene_number=number,
        title=f"Scene {number}",
        narration=narration,
        visual_prompt=f"Visual {number}.",
        estimated_duration_seconds=4,
    )


def _entry(
    number: int, location: str = "A kitchen", on_screen: list[str] | None = None
) -> ClipContinuityEntry:
    return ClipContinuityEntry(
        scene_number=number,
        incoming_state=VisualState(),
        shot_action="x",
        outgoing_state=VisualState(location=location, lighting="Warm light"),
        entity_names=["Kitchen"],
        on_screen_entity_names=on_screen or [],
    )


def _shot(
    number: int, composition: str = "Honey jar.", action: str = "A jar."
) -> ShotSpecification:
    return ShotSpecification(
        scene_number=number,
        shot_size=ShotSize.WIDE,
        shot_angle=ShotAngle.EYE_LEVEL,
        movement=ShotMovement.STATIC,
        lens="35mm",
        composition=composition,
        blocking="n/a",
        lighting="Warm",
        action=action,
        transition_in="cut",
        transition_out="cut",
        duration_seconds=4.0,
    )


def _bible(entries: list[ClipContinuityEntry], *, reference: bool = True):  # type: ignore[no-untyped-def]
    return VisualContinuityBible(
        script_lock_hash="a" * 64,
        identities=[
            CanonicalEntityIdentity(
                entity_type=CanonicalEntityType.PERSON,
                name="Adults",
                canonical_description="Adults who take honey.",
            ),
            CanonicalEntityIdentity(
                entity_type=CanonicalEntityType.LOCATION,
                name="Kitchen",
                canonical_description="A warm family kitchen.",
                reference_asset_ids=["ref-1"] if reference else [],
            ),
        ],
        clip_entries=entries,
    )


# ---- detection ---------------------------------------------------------


def test_the_plans_own_words_for_a_graphic_are_recognised() -> None:
    graphic = _entry(1, "Not shown as kitchen; informational graphic/overlay")

    assert is_graphic_scene(entry=graphic, shot=None)
    assert is_graphic_scene(
        entry=None, shot=_shot(1, composition="Clean diagram recap")
    )
    assert is_graphic_scene(entry=None, shot=_shot(1, action="Icons appear one by one"))
    assert is_graphic_scene(
        entry=None, shot=_shot(1, composition="On-screen text card")
    )


def test_an_ordinary_filmed_scene_is_not_called_a_graphic() -> None:
    assert not is_graphic_scene(entry=_entry(1, "A rural village"), shot=_shot(1))
    assert not is_graphic_scene(entry=None, shot=None)


def test_a_scene_switched_to_live_footage_no_longer_renders_as_a_graphic() -> None:
    entry = _entry(1, "informational graphic/overlay")
    scene = _scene(1)

    assert renders_as_graphic(scene=scene, entry=entry, shot=None)

    scene.treat_as_live_footage = True

    assert not renders_as_graphic(scene=scene, entry=entry, shot=None)
    assert is_graphic_scene(entry=entry, shot=None)  # still what the plan wrote


def test_the_exact_text_is_the_narration_as_written() -> None:
    assert exact_text_for(_scene(1, "  Evidence   in adults\n is limited. ")) == (
        "Evidence in adults is limited."
    )


def test_a_long_narration_is_cut_at_a_word_boundary() -> None:
    text = exact_text_for(_scene(1, "word " * 80))

    assert len(text) <= 165
    assert text.endswith("...")
    assert not text.removesuffix("...").endswith("wor")


# ---- the project's main place ------------------------------------------


def test_the_main_place_is_a_place_not_a_person() -> None:
    place = main_place(_bible([]))

    assert place is not None and place.name == "Kitchen"


def test_a_place_with_a_reference_is_preferred() -> None:
    bible = _bible([])
    bible.identities.insert(
        0,
        CanonicalEntityIdentity(
            entity_type=CanonicalEntityType.LOCATION,
            name="Garage",
            canonical_description="A garage.",
        ),
    )

    place = main_place(bible)

    assert place is not None and place.name == "Kitchen"


def test_no_place_means_no_main_place() -> None:
    bible = _bible([])
    bible.identities = [i for i in bible.identities if i.name == "Adults"]

    assert main_place(bible) is None


def test_a_live_footage_scene_counts_the_main_place_as_on_screen() -> None:
    bible = _bible([_entry(1, on_screen=[]), _entry(2, on_screen=["Adults"])])
    graphic, filmed = _scene(1), _scene(2)

    assert effective_on_screen_names(bible, graphic) == []

    graphic.treat_as_live_footage = True

    assert effective_on_screen_names(bible, graphic) == ["Kitchen"]
    assert effective_on_screen_names(bible, filmed) == ["Adults"]  # unchanged


def test_the_place_is_not_listed_twice() -> None:
    bible = _bible([_entry(1, on_screen=["Kitchen"])])
    scene = _scene(1)
    scene.treat_as_live_footage = True

    assert effective_on_screen_names(bible, scene) == ["Kitchen"]


# ---- the compiled prompt -----------------------------------------------


def _compile(  # type: ignore[no-untyped-def]
    scene: Scene,
    entry: ClipContinuityEntry,
    look: ProjectLook | None = None,
    *,
    graphic_shot: bool = True,
):
    plan = CinematicShotPlan(
        script_lock_hash="a" * 64,
        shots=[
            _shot(
                scene.scene_number,
                composition=(
                    "Clean graphic/text overlay composition"
                    if graphic_shot
                    else "Wide view of the village"
                ),
                action=(
                    "Text appears with icons" if graphic_shot else "The camera holds"
                ),
            )
        ],
    )

    return CinematicPromptCompilationService().compile(
        scenes=[scene],
        shot_plan=plan,
        visual_continuity_bible=_bible([entry]),
        production_semantic_brief=None,
        script_lock_hash="a" * 64,
        project_look=look,
    )


_GRAPHIC_ENTRY = _entry(1, "Not shown as kitchen; informational graphic/overlay")


def test_a_graphic_scenes_prompt_names_the_only_words_allowed_on_screen() -> None:
    prompt = _compile(_scene(1), _GRAPHIC_ENTRY).prompt_for_scene(1)

    assert prompt is not None
    assert _STANDARD not in prompt.negative_constraints
    assert prompt.negative_constraints[0] == (
        'any text on screen must be exactly: "Evidence in adults is limited." - '
        "no other words, numbers, claims or logos"
    )
    # the other standard "do not" lines are untouched
    assert len(prompt.negative_constraints) == 4
    assert "no identity drift" in prompt.negative_constraints[1]


def test_a_filmed_scene_keeps_the_standard_no_text_line() -> None:
    prompt = _compile(
        _scene(1), _entry(1, "A rural village"), graphic_shot=False
    ).prompt_for_scene(1)

    assert prompt is not None
    assert prompt.negative_constraints[0] == _STANDARD


def test_every_part_of_a_split_graphic_scene_gets_the_exact_text_rule() -> None:
    plan = CinematicShotPlan(
        script_lock_hash="a" * 64,
        shots=[_shot(1, composition="Clean diagram recap")],
    )

    prompts = CinematicPromptCompilationService().compile_sub_clip_prompts(
        scene=_scene(1),
        shot_plan=plan,
        visual_continuity_bible=_bible([_GRAPHIC_ENTRY]),
        production_semantic_brief=None,
        script_lock_hash="a" * 64,
        sub_clip_durations=[2.0, 2.0],
    )

    assert all("must be exactly" in p.negative_constraints[0] for p in prompts)


def test_a_scene_switched_to_live_footage_is_filmed_in_the_main_setting() -> None:
    scene = _scene(1, "Evidence in adults is limited.")
    scene.treat_as_live_footage = True

    prompt = _compile(
        scene, _GRAPHIC_ENTRY, look=ProjectLook(lighting="overcast soft daylight")
    ).prompt_for_scene(1)

    assert prompt is not None
    text = prompt.prompt_text
    assert "Environment: Kitchen." in text
    assert "A warm family kitchen." in text  # the setting's own description
    assert "Lighting: overcast soft daylight." in text  # the project's look
    assert (
        "Live-action footage that illustrates: Evidence in adults is limited." in text
    )
    assert "graphic" not in text.lower().replace("graphic scene", "")
    assert "informational" not in text
    assert prompt.negative_constraints[0] == _STANDARD  # filmed: no text, as normal


def test_the_graphics_timed_beats_are_not_used_for_live_footage() -> None:
    from src.models.shot_planning import TemporalActionBeat

    scene = _scene(1)
    scene.treat_as_live_footage = True
    plan = CinematicShotPlan(
        script_lock_hash="a" * 64,
        shots=[
            _shot(1).model_copy(
                update={
                    "temporal_action_beats": [
                        TemporalActionBeat(
                            start_offset_seconds=0,
                            end_offset_seconds=4,
                            description="Text card fades in",
                        )
                    ]
                }
            )
        ],
    )

    prompt = (
        CinematicPromptCompilationService()
        .compile(
            scenes=[scene],
            shot_plan=plan,
            visual_continuity_bible=_bible([_GRAPHIC_ENTRY]),
            production_semantic_brief=None,
            script_lock_hash="a" * 64,
        )
        .prompt_for_scene(1)
    )

    assert prompt is not None
    assert "Text card fades in" not in prompt.prompt_text


def test_live_footage_carries_the_main_places_reference() -> None:
    scene = _scene(1)
    scene.treat_as_live_footage = True

    prompt = _compile(scene, _GRAPHIC_ENTRY).prompt_for_scene(1)

    assert prompt is not None
    assert "ref-1" in prompt.reference_asset_ids


def test_switching_back_restores_the_graphic_rules() -> None:
    scene = _scene(1)
    scene.treat_as_live_footage = True
    scene.treat_as_live_footage = False

    prompt = _compile(scene, _GRAPHIC_ENTRY).prompt_for_scene(1)

    assert prompt is not None
    assert "must be exactly" in prompt.negative_constraints[0]
    assert "Live-action footage" not in prompt.prompt_text


def test_with_no_place_in_the_bible_live_footage_still_compiles() -> None:
    scene = _scene(1)
    scene.treat_as_live_footage = True
    bible = _bible([_GRAPHIC_ENTRY])
    bible.identities = [i for i in bible.identities if i.name == "Adults"]
    plan = CinematicShotPlan(script_lock_hash="a" * 64, shots=[_shot(1)])

    prompt = (
        CinematicPromptCompilationService()
        .compile(
            scenes=[scene],
            shot_plan=plan,
            visual_continuity_bible=bible,
            production_semantic_brief=None,
            script_lock_hash="a" * 64,
        )
        .prompt_for_scene(1)
    )

    assert prompt is not None
    assert "Live-action footage" in prompt.prompt_text


def test_a_project_saved_before_the_switch_existed_still_loads() -> None:
    data = _scene(1).model_dump(mode="json")
    data.pop("treat_as_live_footage")

    assert Scene.model_validate(data).treat_as_live_footage is False


# ---- the Clips tab -----------------------------------------------------


def _flush() -> None:
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _view_with_graphic_scene(recompile=None):  # type: ignore[no-untyped-def]
    job = _job(1, 2)
    job.visual_continuity_bible = _bible([_GRAPHIC_ENTRY, _entry(2, "A rural village")])
    job.visual_continuity_bible.clip_entries[1].scene_number = 2
    job.cinematic_prompt_package = MagicMock()
    view = _build_view(job, service=_FakeSceneVideoGenerationService())
    view._recompile_prompts = recompile  # type: ignore[assignment]  # noqa: SLF001
    view.refresh(job)
    _flush()

    return view, job


def _checkboxes(view) -> list[QCheckBox]:  # type: ignore[no-untyped-def]
    _flush()

    return [
        c
        for c in view.findChildren(QCheckBox)
        if c.text() == "Show as live footage instead of a graphic"
    ]


def test_only_the_graphic_scene_offers_the_switch(
    qapp: QApplication,  # noqa: F811
) -> None:
    view, _ = _view_with_graphic_scene()

    assert len(_checkboxes(view)) == 1
    assert any("Graphic scene" in label.text() for label in view.findChildren(QLabel))


def test_the_switch_starts_off(qapp: QApplication) -> None:  # noqa: F811
    view, job = _view_with_graphic_scene()

    assert not _checkboxes(view)[0].isChecked()
    assert not any(s.treat_as_live_footage for s in job.scenes)


def test_turning_it_on_sets_the_scene_and_rebuilds_the_prompts(
    qapp: QApplication,  # noqa: F811
) -> None:
    recompiled: list[bool] = []
    view, job = _view_with_graphic_scene(
        recompile=lambda j: recompiled.append(
            next(s for s in j.scenes if s.scene_number == 1).treat_as_live_footage
        )
    )

    _checkboxes(view)[0].setChecked(True)

    assert job.scenes[0].treat_as_live_footage is True
    assert recompiled == [True]  # rebuilt AFTER the flag was set


def test_turning_it_off_again_rebuilds_the_prompts_again(
    qapp: QApplication,  # noqa: F811
) -> None:
    recompiled: list[bool] = []
    view, job = _view_with_graphic_scene(
        recompile=lambda j: recompiled.append(j.scenes[0].treat_as_live_footage)
    )
    job.scenes[0].treat_as_live_footage = True
    view.refresh(job)

    _checkboxes(view)[0].setChecked(False)

    assert job.scenes[0].treat_as_live_footage is False
    assert recompiled == [False]


def test_a_scene_already_on_live_footage_says_so(
    qapp: QApplication,  # noqa: F811
) -> None:
    view, job = _view_with_graphic_scene()
    job.scenes[0].treat_as_live_footage = True
    view.refresh(job)
    _flush()

    assert any(
        "Shown as live footage" in label.text() for label in view.findChildren(QLabel)
    )
    assert _checkboxes(view)[0].isChecked()


def test_the_switch_is_saved_with_the_project(
    qapp: QApplication,  # noqa: F811
) -> None:
    view, job = _view_with_graphic_scene()

    _checkboxes(view)[0].setChecked(True)

    assert view._job_store.added  # noqa: SLF001
    assert (
        view._job_store.added[-1].scenes[0].treat_as_live_footage is True
    )  # noqa: SLF001


def test_with_nothing_compiled_yet_the_switch_does_not_try_to_rebuild(
    qapp: QApplication,  # noqa: F811
) -> None:
    calls: list[int] = []
    view, job = _view_with_graphic_scene(recompile=lambda j: calls.append(1))
    job.cinematic_prompt_package = None

    _checkboxes(view)[0].setChecked(True)

    assert calls == []
    assert job.scenes[0].treat_as_live_footage is True


def test_a_failed_rebuild_is_reported_and_the_change_is_not_saved(
    qapp: QApplication,  # noqa: F811
) -> None:
    from unittest.mock import patch

    def boom(j):  # type: ignore[no-untyped-def]
        raise RuntimeError("needs a shot plan")

    view, job = _view_with_graphic_scene(recompile=boom)

    with patch("src.desktop.views.clip_workspace_view.show_recoverable_error") as shown:
        _checkboxes(view)[0].setChecked(True)

    assert shown.called
    assert "needs a shot plan" in str(shown.call_args)
    assert not view._job_store.added  # noqa: SLF001


# ---- the rule is IN the prompt (the constraint list is never sent to Muse or Flow)


def test_a_graphic_scenes_prompt_text_carries_the_on_screen_text_rule() -> None:
    """Live, 2026-10-07: the exact-text rule only lived in the stored constraint list,
    which no provider sends - so Muse wrote its own text ("safely", an invented
    "Source:" line, a "Trusted Info" badge). The rule is now part of the prompt."""

    prompt = _compile(_scene(1), _GRAPHIC_ENTRY).prompt_for_scene(1)

    assert prompt is not None
    assert prompt.prompt_text.endswith(
        'Keep its qualifiers such as "can", "may" and "modestly".'
    )
    assert (
        "On-screen text rule: use only the words of this narration: "
        '"Evidence in adults is limited."' in prompt.prompt_text
    )
    assert "add no other words, numbers, sources, citations, badges" in (
        prompt.prompt_text
    )
    assert "make no claim stronger than the narration's own wording" in (
        prompt.prompt_text
    )


def test_a_filmed_scenes_prompt_text_has_no_text_rule() -> None:
    prompt = _compile(
        _scene(1), _entry(1, "A rural village"), graphic_shot=False
    ).prompt_for_scene(1)

    assert prompt is not None
    assert "On-screen text rule" not in prompt.prompt_text


def test_every_part_of_a_split_graphic_scene_carries_the_text_rule_in_its_prompt() -> (
    None
):
    plan = CinematicShotPlan(
        script_lock_hash="a" * 64,
        shots=[_shot(1, composition="Clean diagram recap")],
    )

    prompts = CinematicPromptCompilationService().compile_sub_clip_prompts(
        scene=_scene(1),
        shot_plan=plan,
        visual_continuity_bible=_bible([_GRAPHIC_ENTRY]),
        production_semantic_brief=None,
        script_lock_hash="a" * 64,
        sub_clip_durations=[2.0, 2.0],
    )

    assert len(prompts) == 2
    assert all("On-screen text rule" in p.prompt_text for p in prompts)


def test_a_vertical_graphic_prompt_ends_with_the_vertical_sentence_after_the_rule() -> (
    None
):
    from src.models.specification_enums import AspectRatio
    from src.models.video_provider import VideoProvider
    from src.services.video_provider_rules import MUSE_PORTRAIT_SENTENCE, rules_for

    prompt = _compile(_scene(1), _GRAPHIC_ENTRY).prompt_for_scene(1)
    assert prompt is not None

    text = rules_for(VideoProvider.MUSE).finalize_prompt(
        prompt.prompt_text, 8.0, AspectRatio.PORTRAIT
    )

    assert text.endswith(MUSE_PORTRAIT_SENTENCE)
    assert text.index("On-screen text rule") < text.index(MUSE_PORTRAIT_SENTENCE)
    assert "Duration: 8 seconds" in text
