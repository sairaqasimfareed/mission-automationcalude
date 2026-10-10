"""
The operator's scene visuals reach every step that decides what a scene shows (2026-10-10). A visual is
an instruction, not a suggestion: the continuity bible treats what it names as on screen, shot planning
must show it, the scene text is built around it, and the compiled prompt's Action IS it. A visual written
for narration that has since changed is stale and ignored everywhere.
"""

from __future__ import annotations

import inspect

from src.models.scene_visual import SceneVisual, SceneVisualPlan, narration_key
from src.services import (
    muse_scene_video_generation_service,
    scene_video_generation_service,
)
from src.services.cinematic_prompt_compilation_service import (
    CinematicPromptCompilationService,
)
from src.services.content_intelligence_pipeline import ContentIntelligencePipeline
from src.services.scene_detail_service import SceneDetailService
from src.services.shot_planning_service import ShotPlanningService
from src.services.visual_continuity_service import VisualContinuityService
from tests.test_cinematic_prompt_compilation_service import _bible, _scene, _shot_plan
from tests.test_scene_detail import _job

_VISUAL = "A pale figure stands in the doorway, half in shadow, eyes faintly lit"


def _plan_for(job, text: str = _VISUAL, number: int = 1) -> SceneVisualPlan:  # type: ignore[no-untyped-def]
    scene = next(s for s in job.scenes if s.scene_number == number)

    return SceneVisualPlan(
        visuals=[
            SceneVisual(
                scene_number=number,
                text=text,
                narration_key=narration_key(scene.narration),
            )
        ]
    )


# ------------------------------------------------------------------------------ job


def test_the_job_exposes_only_current_visuals() -> None:
    job = _job(3)

    assert job.current_scene_visuals == {}

    job.scene_visual_plan = _plan_for(job)

    assert job.current_scene_visuals == {1: _VISUAL}

    job.scenes[0].narration = "Changed narration."

    assert job.current_scene_visuals == {}


def test_a_job_saved_before_visuals_existed_loads() -> None:
    from src.models.video_job import VideoJob

    job = VideoJob(project_name="P", channel_name="C", niche="n", topic="T")
    data = job.model_dump(mode="json")
    data.pop("scene_visual_plan", None)

    assert VideoJob.model_validate(data).scene_visual_plan is None


# ------------------------------------------------------------------------- compiler


def _compile(visuals: dict[int, str] | None, *, live_footage: bool = False) -> str:
    scene = _scene(1)
    scene.treat_as_live_footage = live_footage
    package = CinematicPromptCompilationService().compile(
        scenes=[scene],
        shot_plan=_shot_plan(),
        visual_continuity_bible=_bible(),
        production_semantic_brief=None,
        script_lock_hash="hash123",
        scene_visuals=visuals,
    )
    prompt = package.prompt_for_scene(1)
    assert prompt is not None

    return prompt.prompt_text


def test_the_operators_visual_replaces_the_planned_action() -> None:
    planned = _shot_plan().shot_for_scene(1)
    assert planned is not None

    without = _compile(None)
    with_visual = _compile({1: _VISUAL})

    assert f"Action progression: {_VISUAL}" in with_visual or _VISUAL in with_visual
    assert planned.action in without
    assert planned.action not in with_visual


def _compile_with_beats(visual_revision: str) -> str:
    from src.models.shot_planning import TemporalActionBeat
    from tests.test_cinematic_prompt_compilation_service import _shot_plan_with_beats

    plan = _shot_plan_with_beats(
        [
            TemporalActionBeat(
                start_offset_seconds=0.0,
                end_offset_seconds=4.0,
                description="push in on the letter",
            ),
            TemporalActionBeat(
                start_offset_seconds=4.0,
                end_offset_seconds=8.0,
                description="hold on the ink",
            ),
        ]
    )
    plan.visual_revision = visual_revision
    package = CinematicPromptCompilationService().compile(
        scenes=[_scene(1)],
        shot_plan=plan,
        visual_continuity_bible=_bible(),
        production_semantic_brief=None,
        script_lock_hash="hash123",
        scene_visuals={1: _VISUAL},
    )
    prompt = package.prompt_for_scene(1)
    assert prompt is not None

    return prompt.prompt_text


def test_beats_planned_without_the_visuals_are_dropped_so_they_cannot_contradict_it() -> (
    None
):
    text = _compile_with_beats("")

    assert "push in on the letter" not in text
    assert "Shot progression" not in text
    assert text.count(_VISUAL) == 1


def test_beats_planned_with_the_visuals_are_kept_after_an_on_screen_sentence() -> None:
    text = _compile_with_beats("rev1")

    assert "push in on the letter" in text
    assert f"On screen: {_VISUAL}." in text
    assert text.index("On screen:") < text.index("Shot progression")


def test_a_scene_with_no_visual_compiles_exactly_as_before() -> None:
    assert _compile({2: "elsewhere"}) == _compile(None)


def test_a_scene_switched_to_live_footage_still_shows_the_operators_visual() -> None:
    """A described scene is filmed: the visual replaces the 'live-action footage that illustrates the
    narration' wording that a footage scene would otherwise get (changed 2026-10-10 with the graphic fix).
    """

    text = _compile({1: _VISUAL}, live_footage=True)

    assert _VISUAL in text
    assert "Live-action footage that illustrates" not in text


def test_a_footage_scene_with_no_visual_keeps_its_own_wording() -> None:
    assert "Live-action footage that illustrates" in _compile(None, live_footage=True)


def test_every_sub_clip_of_a_split_scene_carries_the_visual() -> None:
    prompts = CinematicPromptCompilationService().compile_sub_clip_prompts(
        scene=_scene(1),
        shot_plan=_shot_plan(),
        visual_continuity_bible=_bible(),
        production_semantic_brief=None,
        script_lock_hash="hash123",
        sub_clip_durations=[6.0, 6.0],
        scene_visuals={1: _VISUAL},
    )

    assert len(prompts) == 2
    assert all(_VISUAL in p.prompt_text for p in prompts)


# ------------------------------------------------------------------------ the prompts


def test_the_continuity_prompt_carries_the_visual_and_the_on_screen_rule() -> None:
    job = _job(2)
    with_visual = VisualContinuityService._build_prompt(  # noqa: SLF001
        job.scenes,
        _continuity_bible(),
        "",
        {1: _VISUAL},
    )
    without = VisualContinuityService._build_prompt(  # noqa: SLF001
        job.scenes, _continuity_bible(), "", None
    )

    assert (
        f"REQUIRED ON-SCREEN VISUAL (the operator's own instruction): {_VISUAL}"
        in with_visual
    )
    assert "counts as present and on screen" in with_visual
    assert "REQUIRED ON-SCREEN VISUAL" not in without


def _continuity_bible():  # type: ignore[no-untyped-def]
    from src.models.continuity_bible import ContinuityBible

    return ContinuityBible(topic="T", prompt_version="v")


def test_the_shot_planning_prompt_requires_the_visual_for_that_scene_only() -> None:
    from tests.test_shot_planning_service import _bible as shot_bible
    from tests.test_shot_planning_service import _scene as shot_scene

    prompt = ShotPlanningService._build_prompt(  # noqa: SLF001
        [shot_scene(1), shot_scene(2)],
        shot_bible(),
        "Topic",
        scene_visuals={2: _VISUAL},
    )

    assert prompt.count("REQUIRED ON-SCREEN VISUAL") == 1
    assert prompt.index("REQUIRED ON-SCREEN VISUAL") > prompt.index("SCENE 2")
    assert _VISUAL in prompt
    assert "make ACTION this visual" in prompt


def test_the_scene_text_prompt_is_built_around_the_visual() -> None:
    job = _job(3)
    job.scene_visual_plan = _plan_for(job, number=2)

    prompt = SceneDetailService._build_prompt(job, job.scenes)  # noqa: SLF001

    assert prompt.count("REQUIRED ON-SCREEN VISUAL") == 1
    assert _VISUAL in prompt
    assert prompt.index("REQUIRED ON-SCREEN VISUAL") > prompt.index("SCENE 2")
    assert prompt.index("REQUIRED ON-SCREEN VISUAL") < prompt.index("SCENE 3")


def test_a_stale_visual_is_not_sent_to_the_scene_text_prompt() -> None:
    job = _job(3)
    job.scene_visual_plan = _plan_for(job, number=2)
    job.scenes[1].narration = "Different narration now."

    prompt = SceneDetailService._build_prompt(job, job.scenes)  # noqa: SLF001

    assert "REQUIRED ON-SCREEN VISUAL" not in prompt


# ---------------------------------------------------------------------------- pipeline


def _pipeline_with_stub():  # type: ignore[no-untyped-def]
    from tests.test_content_intelligence_pipeline import _EchoStubLLMService

    stub = _EchoStubLLMService()

    return ContentIntelligencePipeline(llm_service=stub), stub  # type: ignore[arg-type]


def _full_job(pipeline):  # type: ignore[no-untyped-def]
    from tests.test_content_intelligence_pipeline import _job as pipeline_job

    return pipeline.run_all(pipeline_job(genre_id="genre.horror"))


def test_applying_visuals_stores_them_and_removes_them_when_cleared() -> None:
    pipeline, _ = _pipeline_with_stub()
    job = _full_job(pipeline)
    plan = _plan_for(job)

    pipeline.apply_scene_visuals(job, plan)

    assert job.scene_visual_plan is plan
    assert job.current_scene_visuals == {1: _VISUAL}

    pipeline.apply_scene_visuals(job, SceneVisualPlan())

    assert job.scene_visual_plan is None

    pipeline.apply_scene_visuals(job, plan)
    pipeline.apply_scene_visuals(job, None)

    assert job.scene_visual_plan is None


def test_applying_visuals_recompiles_the_prompts_without_a_model_call() -> None:
    pipeline, stub = _pipeline_with_stub()
    job = _full_job(pipeline)
    assert job.cinematic_prompt_package is not None
    calls_before = len(stub.requests)

    pipeline.apply_scene_visuals(job, _plan_for(job))

    prompt = job.cinematic_prompt_package.prompt_for_scene(1)  # type: ignore[union-attr]
    assert prompt is not None and _VISUAL in prompt.prompt_text
    assert len(stub.requests) == calls_before


def test_rebuilding_asks_the_bible_the_shot_plan_and_the_scene_text_to_follow_the_visuals() -> (
    None
):
    pipeline, stub = _pipeline_with_stub()
    job = _full_job(pipeline)
    pipeline.apply_scene_visuals(job, _plan_for(job))
    stub.requests.clear()

    pipeline.rebuild_for_scene_visuals(job)

    carrying = {
        str(r.metadata.get("agent"))
        for r in stub.requests
        if "REQUIRED ON-SCREEN VISUAL" in r.prompt
    }

    assert {"VisualContinuityService", "ShotPlanningService"} <= carrying


def test_the_shot_plan_records_which_visuals_it_was_made_with() -> None:
    pipeline, _ = _pipeline_with_stub()
    job = _full_job(pipeline)

    assert job.cinematic_shot_plan is not None
    assert job.cinematic_shot_plan.visual_revision == ""

    plan = _plan_for(job)
    pipeline.apply_scene_visuals(job, plan)
    pipeline.run_shot_planning(job)

    assert job.cinematic_shot_plan.visual_revision == plan.revision


# ------------------------------------------------------------------ generation services


def test_both_generation_services_hand_the_visuals_to_the_compiler() -> None:
    """The prompt actually sent to Muse / Flow is compiled again at generation time, so these
    call sites must pass the visuals too or a clip would be generated without them."""

    for module in (scene_video_generation_service, muse_scene_video_generation_service):
        source = inspect.getsource(module)

        assert "scene_visuals=job.current_scene_visuals" in source, module.__name__
