"""
Project look (2026-10-07): lighting, colour palette and camera feel written once and
repeated word for word in every scene's prompt.

Live, 2026-10-06 (Lake Nyos): scene 1 came out overcast and muted, scene 2 sunny and
saturated, because each prompt carried only its own vague lighting phrase.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import patch  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402
from PySide6.QtWidgets import (
    QApplication,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)  # noqa: E402

from src.models.project_look import ProjectLook  # noqa: E402
from src.models.scene import Scene  # noqa: E402
from src.models.shot_planning import (  # noqa: E402
    CinematicShotPlan,
    ShotAngle,
    ShotMovement,
    ShotSize,
    ShotSpecification,
)
from src.models.video_job import VideoJob  # noqa: E402
from src.models.visual_continuity import (  # noqa: E402
    ClipContinuityEntry,
    VisualContinuityBible,
    VisualState,
)
from src.services.cinematic_prompt_compilation_service import (  # noqa: E402
    CinematicPromptCompilationService,
)
from tests.test_content_studio_content_intelligence_gui import (  # noqa: E402
    _job,
    _view,
)
from tests.test_content_studio_content_intelligence_gui import (  # noqa: E402
    qapp as qapp,  # noqa: PLC0414 - fixture
)

_LOOK = ProjectLook(
    lighting="overcast soft daylight",
    color_palette="muted, desaturated documentary colours",
    camera_feel="handheld documentary realism",
)


# ---- the model ---------------------------------------------------------


def test_a_look_with_nothing_set_is_empty_and_says_nothing() -> None:
    look = ProjectLook()

    assert look.is_empty
    assert look.as_prompt_sentence() == ""


def test_the_sentence_names_each_part_that_is_set() -> None:
    assert _LOOK.as_prompt_sentence() == (
        "Visual style for the whole video - lighting: overcast soft daylight; "
        "colour palette: muted, desaturated documentary colours; camera feel: "
        "handheld documentary realism."
    )


def test_only_the_parts_that_are_set_appear() -> None:
    sentence = ProjectLook(lighting="soft light").as_prompt_sentence()

    assert sentence == "Visual style for the whole video - lighting: soft light."
    assert "palette" not in sentence


def test_stray_whitespace_and_a_trailing_full_stop_are_cleaned() -> None:
    look = ProjectLook(lighting="  soft   overcast\n light. ")

    assert look.lighting == "soft overcast light"


def test_a_field_cannot_run_on_forever() -> None:
    with pytest.raises(ValueError):
        ProjectLook(lighting="x" * 201)


def test_a_look_made_only_of_spaces_counts_as_empty() -> None:
    assert ProjectLook(lighting="   ", camera_feel=" . ").is_empty


# ---- compiled into every prompt ---------------------------------------


def _scene(number: int) -> Scene:
    return Scene(
        scene_number=number,
        title=f"Scene {number}",
        narration=f"Narration {number}.",
        visual_prompt=f"Visual {number}.",
        estimated_duration_seconds=8,
    )


def _inputs(numbers: list[int]):  # type: ignore[no-untyped-def]
    plan = CinematicShotPlan(
        script_lock_hash="a" * 64,
        shots=[
            ShotSpecification(
                scene_number=n,
                shot_size=ShotSize.WIDE,
                shot_angle=ShotAngle.EYE_LEVEL,
                movement=ShotMovement.STATIC,
                lens="35mm",
                composition="Wide village view.",
                blocking="n/a",
                lighting=f"scene {n} lighting",
                action=f"Action {n}.",
                transition_in="cut",
                transition_out="cut",
                duration_seconds=8.0,
            )
            for n in numbers
        ],
    )
    bible = VisualContinuityBible(
        script_lock_hash="a" * 64,
        identities=[],
        clip_entries=[
            ClipContinuityEntry(
                scene_number=n,
                incoming_state=VisualState(),
                shot_action="x",
                outgoing_state=VisualState(
                    location="A village", lighting=f"Natural daylight {n}"
                ),
            )
            for n in numbers
        ],
    )

    return plan, bible


def _compile(look: ProjectLook | None, numbers: list[int] | None = None):  # type: ignore[no-untyped-def]
    numbers = numbers or [1, 2]
    plan, bible = _inputs(numbers)

    return CinematicPromptCompilationService().compile(
        scenes=[_scene(n) for n in numbers],
        shot_plan=plan,
        visual_continuity_bible=bible,
        production_semantic_brief=None,
        script_lock_hash="a" * 64,
        project_look=look,
    )


def test_every_scenes_prompt_carries_the_same_look_sentence() -> None:
    package = _compile(_LOOK)

    for n in (1, 2):
        prompt = package.prompt_for_scene(n)
        assert prompt is not None
        assert _LOOK.as_prompt_sentence() in prompt.prompt_text


def test_the_look_does_not_replace_a_scenes_own_lighting_line() -> None:
    package = _compile(_LOOK)
    prompt = package.prompt_for_scene(2)

    assert prompt is not None
    assert "Lighting: Natural daylight 2." in prompt.prompt_text  # still its own


def test_the_look_sits_before_the_duration_so_the_duration_line_still_works() -> None:
    prompt = _compile(_LOOK).prompt_for_scene(1)

    assert prompt is not None
    text = prompt.prompt_text
    assert text.index("Visual style for the whole video") < text.index("Duration:")
    assert "Duration: 8 seconds." in text

    # the real sizing step rewrites that line to the clip's real length, even with the
    # "do not show text" sentence now following it
    from src.models.video_provider import VideoProvider
    from src.services.video_provider_rules import rules_for

    rewritten = rules_for(VideoProvider.GOOGLE_FLOW).finalize_prompt(text, 6)

    assert "Duration: 6 seconds" in rewritten
    assert "Duration: 8 seconds" not in rewritten


def test_without_a_look_the_prompt_is_exactly_what_it_was() -> None:
    with_none = _compile(None).prompt_for_scene(1)
    with_empty = _compile(ProjectLook()).prompt_for_scene(1)

    assert with_none is not None and with_empty is not None
    assert "Visual style" not in with_none.prompt_text
    assert with_empty.prompt_text == with_none.prompt_text


def test_every_part_of_a_split_scene_carries_the_look() -> None:
    plan, bible = _inputs([1])
    prompts = CinematicPromptCompilationService().compile_sub_clip_prompts(
        scene=_scene(1),
        shot_plan=plan,
        visual_continuity_bible=bible,
        production_semantic_brief=None,
        script_lock_hash="a" * 64,
        sub_clip_durations=[4.0, 4.0],
        project_look=_LOOK,
    )

    assert len(prompts) == 2
    assert all(_LOOK.as_prompt_sentence() in p.prompt_text for p in prompts)


def test_the_look_survives_saving_and_reloading_the_project() -> None:
    job = _job()
    job.project_look = _LOOK

    reloaded = VideoJob.model_validate_json(job.model_dump_json())

    assert reloaded.project_look == _LOOK


def test_a_project_saved_before_the_look_existed_still_loads() -> None:
    job = _job()
    data = job.model_dump(mode="json")
    data.pop("project_look")

    assert VideoJob.model_validate(data).project_look is None


# ---- the Content Studio form ------------------------------------------


def _flush() -> None:
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_the_form_shows_three_separate_fields_filled_from_the_project(
    qapp: QApplication,  # noqa: F811
) -> None:
    from src.desktop.job_store import InMemoryJobStore

    store = InMemoryJobStore()
    job = _job()
    job.project_look = _LOOK
    store.add(job)
    view = _view(store)
    view.set_job(job.id)
    holder = QWidget()
    layout = QVBoxLayout(holder)

    view._render_project_look_section(layout, job)  # noqa: SLF001

    fields = holder.findChildren(QLineEdit)
    assert [f.text() for f in fields] == [
        "overcast soft daylight",
        "muted, desaturated documentary colours",
        "handheld documentary realism",
    ]
    buttons = [b.text() for b in holder.findChildren(QPushButton)]
    assert "Save project look" in buttons
    # the suggested looks sit above the fields, each with Use / Discard
    assert buttons.count("Use this look") == buttons.count("Discard") >= 1


def test_saving_stores_the_look_and_recompiles_the_prompts(
    qapp: QApplication,  # noqa: F811
) -> None:
    from src.desktop.job_store import InMemoryJobStore

    store = InMemoryJobStore()
    job = _job()
    job.cinematic_prompt_package = _compile(None)
    store.add(job)
    view = _view(store)
    view.set_job(job.id)
    recompiled: list[VideoJob] = []

    def fake_recompile(j: VideoJob) -> VideoJob:
        recompiled.append(j)

        return j

    view._content_intelligence_pipeline.run_cinematic_prompt_compilation = fake_recompile  # type: ignore[method-assign]  # noqa: SLF001

    view._apply_project_look(  # noqa: SLF001
        job,
        {
            "lighting": "overcast soft daylight",
            "color_palette": "muted",
            "camera_feel": "",
        },
    )

    assert job.project_look is not None
    assert job.project_look.lighting == "overcast soft daylight"
    assert recompiled == [job]


def test_saving_an_empty_form_clears_the_look(
    qapp: QApplication,  # noqa: F811
) -> None:
    from src.desktop.job_store import InMemoryJobStore

    store = InMemoryJobStore()
    job = _job()
    job.project_look = _LOOK
    store.add(job)
    view = _view(store)
    view.set_job(job.id)

    view._apply_project_look(  # noqa: SLF001
        job, {"lighting": "", "color_palette": " ", "camera_feel": ""}
    )

    assert job.project_look is None


def test_with_nothing_compiled_yet_saving_does_not_try_to_recompile(
    qapp: QApplication,  # noqa: F811
) -> None:
    from src.desktop.job_store import InMemoryJobStore

    store = InMemoryJobStore()
    job = _job()
    assert job.cinematic_prompt_package is None
    store.add(job)
    view = _view(store)
    view.set_job(job.id)

    with patch.object(
        view._content_intelligence_pipeline,  # noqa: SLF001
        "run_cinematic_prompt_compilation",
    ) as recompile:
        view._apply_project_look(  # noqa: SLF001
            job, {"lighting": "soft", "color_palette": "", "camera_feel": ""}
        )

    recompile.assert_not_called()
    assert job.project_look is not None


def test_a_too_long_field_is_reported_and_nothing_is_saved(
    qapp: QApplication,  # noqa: F811
) -> None:
    from src.desktop.job_store import InMemoryJobStore

    store = InMemoryJobStore()
    job = _job()
    store.add(job)
    view = _view(store)
    view.set_job(job.id)

    with patch("src.desktop.views.content_studio_view.show_recoverable_error") as shown:
        view._apply_project_look(  # noqa: SLF001
            job, {"lighting": "x" * 300, "color_palette": "", "camera_feel": ""}
        )

    assert shown.called
    assert job.project_look is None
