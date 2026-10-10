"""
A genre says how a video should FEEL on screen, and the steps that decide the look must hear it
(2026-10-10, live: Haunted wife, genre.horror). The video came out as a calm documentary: the style
sheet drafter never saw the genre (and its prompt offered "documentary" as the example camera
language) and shot planning never saw it either. Now the style sheet drafter, shot planning and the
scene detail writer are given the genre's treatment direction, and the style fields a script gave
nothing for take the genre's own look. Setting, buildings and climate are never filled from a genre.
"""

from __future__ import annotations

import pytest

from src.models.project_look import ProjectLook
from src.services.genre_visual_mood import genre_direction, genre_style_defaults
from src.services.project_style_sheet_service import ProjectStyleSheetService
from src.services.scene_detail_service import SceneDetailService
from src.services.shot_planning_service import ShotPlanningService
from tests.test_scene_detail import _job as _detail_job
from tests.test_scene_detail import _shot_plan
from tests.test_shot_planning_service import _bible, _scene
from tests.test_suggestions import _job, _StubLLM

_NONE = "\n".join(
    f"{label}: NONE"
    for label in (
        "SETTING",
        "BUILDINGS",
        "CLIMATE",
        "LIGHTING",
        "PALETTE",
        "CAMERA",
        "SOUND",
    )
)


# ------------------------------------------------------------------------------- table


def test_horror_has_a_direction_that_is_not_documentary() -> None:
    direction = genre_direction("genre.horror")

    assert "NOT documentary" in direction
    assert "dread" in direction


@pytest.mark.parametrize(
    "genre", ["genre.default", "genre.medical", "genre.comedy", "genre.unknown", ""]
)
def test_a_genre_with_no_mood_has_no_direction_and_no_defaults(genre: str) -> None:
    assert genre_direction(genre) == ""
    assert genre_style_defaults(genre) == {}


def test_the_defaults_are_style_fields_only() -> None:
    defaults = genre_style_defaults("genre.horror")

    assert set(defaults) == {"lighting", "color_palette", "camera_feel", "sound"}
    assert all(defaults.values())
    ProjectLook(**defaults)  # fits the field limits


@pytest.mark.parametrize(
    "genre",
    [
        "genre.horror",
        "genre.mystery",
        "genre.documentary",
        "genre.history",
        "genre.survival",
        "genre.storytelling",
    ],
)
def test_every_mood_fits_the_look_field_limits(genre: str) -> None:
    ProjectLook(**genre_style_defaults(genre))
    assert 50 < len(genre_direction(genre)) < 700


# ----------------------------------------------------------------------- style sheet


def test_the_style_sheet_prompt_carries_the_genre_direction() -> None:
    llm = _StubLLM(_NONE)
    service = ProjectStyleSheetService(llm_service=llm)  # type: ignore[arg-type]

    service.draft(_job("genre.horror"))

    prompt = llm.requests[0].prompt
    assert "Genre treatment" in prompt
    assert genre_direction("genre.horror") in prompt
    assert "documentary, slow push-ins" not in prompt


def test_a_genre_without_a_mood_adds_nothing_to_the_style_sheet_prompt() -> None:
    llm = _StubLLM(_NONE)
    service = ProjectStyleSheetService(llm_service=llm)  # type: ignore[arg-type]

    service.draft(_job("genre.medical"))

    assert "Genre treatment" not in llm.requests[0].prompt


def test_style_fields_the_script_gave_nothing_for_take_the_genre_look() -> None:
    service = ProjectStyleSheetService(llm_service=_StubLLM(_NONE))  # type: ignore[arg-type]

    look = service.draft(_job("genre.horror"))

    assert look.lighting and look.color_palette and look.camera_feel and look.sound
    # facts about the script's world are never filled from a genre
    assert (look.setting, look.architecture, look.climate) == ("", "", "")


def test_what_the_script_did_say_is_kept_over_the_genre_default() -> None:
    reply = _NONE.replace("CAMERA: NONE", "CAMERA: Locked-off wide frames")
    service = ProjectStyleSheetService(llm_service=_StubLLM(reply))  # type: ignore[arg-type]

    look = service.draft(_job("genre.horror"))

    assert look.camera_feel == "Locked-off wide frames"
    assert look.lighting == genre_style_defaults("genre.horror")["lighting"]


def test_a_genre_with_no_mood_still_gives_an_empty_look_for_an_empty_reply() -> None:
    service = ProjectStyleSheetService(llm_service=_StubLLM(_NONE))  # type: ignore[arg-type]

    assert service.draft(_job("genre.medical")).is_empty


# ------------------------------------------------------------------------ shot planning


def test_shot_planning_prompt_carries_the_genre_direction_when_given() -> None:
    prompt = ShotPlanningService._build_prompt(  # noqa: SLF001
        [_scene(1)], _bible(), "Topic", genre_direction=genre_direction("genre.horror")
    )

    assert "Genre treatment" in prompt
    assert genre_direction("genre.horror") in prompt
    assert "without adding any event" in prompt


def test_shot_planning_prompt_is_unchanged_without_a_direction() -> None:
    prompt = ShotPlanningService._build_prompt(  # noqa: SLF001
        [_scene(1)], _bible(), "Topic"
    )

    assert "Genre treatment" not in prompt


# ------------------------------------------------------------------------ scene detail


def test_the_scene_detail_prompt_carries_the_genre_direction() -> None:
    job = _detail_job(2)
    job.genre_id = "genre.horror"
    job.cinematic_shot_plan = _shot_plan()

    prompt = SceneDetailService._build_prompt(job, job.scenes[:1])  # noqa: SLF001

    assert genre_direction("genre.horror") in prompt


def test_the_scene_detail_prompt_has_no_genre_line_for_a_genre_with_no_mood() -> None:
    job = _detail_job(2)
    job.genre_id = "genre.default"
    job.cinematic_shot_plan = _shot_plan()

    prompt = SceneDetailService._build_prompt(job, job.scenes[:1])  # noqa: SLF001

    assert "Genre treatment" not in prompt


# ---------------------------------------------------------------------------- pipeline


def test_the_pipeline_hands_the_job_genre_to_shot_planning() -> None:
    """run_shot_planning passes genre_direction(job.genre_id), so a horror job is planned
    with the horror treatment."""

    from src.services.content_intelligence_pipeline import ContentIntelligencePipeline

    seen: dict[str, str] = {}

    class _Planner:
        def plan(self, **kwargs):  # type: ignore[no-untyped-def]
            seen["direction"] = kwargs["genre_direction"]
            raise RuntimeError("stop after the arguments are captured")

    from tests.test_scene_detail import _job as make_job

    job = make_job(2)
    job.genre_id = "genre.horror"

    pipeline = ContentIntelligencePipeline.__new__(ContentIntelligencePipeline)
    pipeline.shot_planning_service = _Planner()  # type: ignore[assignment]

    from src.models.script_lock import ScriptLock  # noqa: F401

    job.script_lock = job.script_lock or _lock()
    job.visual_continuity_bible = job.visual_continuity_bible or _bible()

    with pytest.raises(RuntimeError, match="stop after"):
        pipeline.run_shot_planning(job)

    assert seen["direction"] == genre_direction("genre.horror")


def _lock():  # type: ignore[no-untyped-def]
    from src.models.script_lock import ScriptLock

    return ScriptLock.model_construct(script_content_hash="hash123")
