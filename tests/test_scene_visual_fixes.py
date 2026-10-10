"""
Three bugs found live while rebuilding Haunted wife with scene visuals (2026-10-10).

1. The scene-text pass lost the last two scenes of a batch: the reply wrote "SCENE 18 DETAIL: ..." on one
   line and the parser only knew two separate lines.
2. Shot planning asked for all 19 scenes in ONE call; with the visuals in the prompt the reply reached the
   16,384-token cap, was cut off, and scene 19 silently got a generic shot ("It was her."). It now plans a
   few scenes per call.
3. A scene whose visual mentioned a title card was classified as a graphic: skipped by the scene-text pass
   and told it could print its narration on screen. A scene the operator described is filmed, never a graphic.
"""

from __future__ import annotations

import logging

import pytest

from src.models.scene import Scene
from src.models.scene_visual import SceneVisual, SceneVisualPlan, narration_key
from src.models.shot_planning import (
    CinematicShotPlan,
    ShotAngle,
    ShotMovement,
    ShotSize,
    ShotSpecification,
)
from src.services.cinematic_prompt_compilation_service import (
    CinematicPromptCompilationService,
)
from src.services.scene_detail_service import SceneDetailService
from src.services.scene_visual_treatment import (
    exact_text_for,
    is_graphic_scene,
    renders_as_graphic,
)
from src.services.shot_planning_service import ShotPlanningService
from tests.test_cinematic_prompt_compilation_service import _bible, _scene
from tests.test_scene_detail import _LONG, _job, _ScriptedLLM

# ----------------------------------------------------------------------- 1. inline format


def _service(llm: _ScriptedLLM) -> SceneDetailService:
    return SceneDetailService(llm_service=llm)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "template",
    [
        "SCENE {n} DETAIL: {text}",
        "SCENE: {n} - DETAIL: {text}",
        "**SCENE {n}** DETAIL: {text}",
        "SCENE: {n}\nDETAIL: {text}",
    ],
)
def test_every_way_of_writing_a_scene_and_its_detail_is_read(template: str) -> None:
    job = _job(2)
    reply = "\n---\n".join(template.format(n=n, text=_LONG) for n in (1, 2))

    plan = _service(_ScriptedLLM([reply])).draft(job)

    assert [d.scene_number for d in plan.details] == [1, 2]
    assert all(d.text.startswith("A low, wide view") for d in plan.details)


def test_a_batch_that_wrote_its_last_scenes_inline_loses_none_of_them() -> None:
    job = _job(3)
    reply = f"SCENE: 1\nDETAIL: {_LONG}\n---\nSCENE 2 DETAIL: {_LONG}\n---\nSCENE 3 DETAIL: {_LONG}"

    plan = _service(_ScriptedLLM([reply])).draft(job)

    assert [d.scene_number for d in plan.details] == [1, 2, 3]


# ----------------------------------------------------------------------- 2. shot batches


def _block(number: int) -> str:
    return (
        f"SCENE: {number}\nSHOT_SIZE: medium\nSHOT_ANGLE: eye_level\nMOVEMENT: static\n"
        f"LENS: 35mm\nCOMPOSITION: Frame {number}.\nBLOCKING: Centre.\nLIGHTING: Dim.\n"
        f"ACTION: Action {number}.\nTRANSITION_IN: cut\nTRANSITION_OUT: cut\n"
        "BEATS: 0-2s: a; 2-8s: b"
    )


class _RecordingLLM:
    """Answers each call with blocks for exactly the scenes that call asked about."""

    def __init__(self, *, skip: set[int] | None = None) -> None:
        self.prompts: list[str] = []
        self.skip = skip or set()

    def generate(self, request, *, estimated_cost_usd=0.0, profile_ids=None):  # type: ignore[no-untyped-def]
        import re

        from src.services.llm.llm_service import LLMServiceResult
        from src.shared.llm.models import LLMCallResult, LLMCallStatus, LLMProvider

        self.prompts.append(request.prompt)
        numbers = [int(n) for n in re.findall(r"^SCENE (\d+) \(", request.prompt, re.M)]
        content = "\n---\n".join(_block(n) for n in numbers if n not in self.skip)
        result = LLMCallResult(
            status=LLMCallStatus.SUCCESS,
            provider=LLMProvider.OPENAI,
            model="m",
            content=content or "none",
        )

        return LLMServiceResult(
            result=result, selected_profile_id="p", all_providers_failed=False
        )


def _scenes(count: int) -> list[Scene]:
    return [_scene(n) for n in range(1, count + 1)]


def _plan(llm, count: int, **kwargs):  # type: ignore[no-untyped-def]
    service = ShotPlanningService(llm_service=llm, **kwargs)
    scenes = _scenes(count)

    return service.plan(
        scenes=scenes,
        visual_continuity_bible=_bible(),
        script_lock_hash="hash123",
        topic="T",
    )


def test_scenes_are_planned_a_few_per_call_and_merged_in_order() -> None:
    llm = _RecordingLLM()

    plan = _plan(llm, 5, batch_size=2)

    assert len(llm.prompts) == 3
    assert [s.scene_number for s in plan.shots] == [1, 2, 3, 4, 5]
    assert all(s.action == f"Action {s.scene_number}." for s in plan.shots)


def test_each_call_asks_only_about_its_own_scenes() -> None:
    llm = _RecordingLLM()

    _plan(llm, 5, batch_size=2)

    assert "SCENE 1 (" in llm.prompts[0] and "SCENE 3 (" not in llm.prompts[0]
    assert "SCENE 3 (" in llm.prompts[1] and "SCENE 1 (" not in llm.prompts[1]
    assert "SCENE 5 (" in llm.prompts[2] and "SCENE 4 (" not in llm.prompts[2]


def test_nineteen_scenes_never_go_in_one_call_by_default() -> None:
    llm = _RecordingLLM()

    plan = _plan(llm, 19)

    assert len(llm.prompts) == 3  # 8 + 8 + 3
    assert len(plan.shots) == 19
    assert plan.shots[-1].action == "Action 19."


def test_a_scene_the_reply_skipped_still_gets_a_shot_and_a_warning(caplog) -> None:  # type: ignore[no-untyped-def]
    llm = _RecordingLLM(skip={4})

    with caplog.at_level(logging.WARNING):
        plan = _plan(llm, 5, batch_size=2)

    assert plan.has_exactly_one_shot_per_scene
    assert plan.shots[3].composition.startswith("Standard framing")


def test_a_failed_batch_fails_the_plan_in_plain_words() -> None:
    from tests.test_shot_planning_service import _StubLLMService

    stub = _StubLLMService(content="", success=False)

    with pytest.raises(RuntimeError, match="Shot planning failed"):
        _plan(stub, 3, batch_size=2)


def test_the_batch_size_must_be_positive() -> None:
    with pytest.raises(ValueError, match="batch size"):
        ShotPlanningService(llm_service=_RecordingLLM(), batch_size=0)  # type: ignore[arg-type]


# ----------------------------------------------------------------------- 3. never a graphic


def _title_card_shot() -> CinematicShotPlan:
    return CinematicShotPlan(
        script_lock_hash="hash123",
        shots=[
            ShotSpecification(
                scene_number=1,
                shot_size=ShotSize.WIDE,
                shot_angle=ShotAngle.EYE_LEVEL,
                movement=ShotMovement.DOLLY,
                lens="24mm",
                composition="A wide room.",
                blocking="Centre.",
                lighting="Dim.",
                action="Slow pull back, then a title card fades in over the room.",
                transition_in="cut",
                transition_out="cut",
                duration_seconds=8.0,
            )
        ],
    )


def test_a_title_card_in_the_plan_makes_a_scene_a_graphic_unless_the_operator_described_it() -> (
    None
):
    scene = _scene(1)
    shot = _title_card_shot().shot_for_scene(1)

    assert is_graphic_scene(entry=None, shot=shot)
    assert renders_as_graphic(scene=scene, entry=None, shot=shot) is True
    assert (
        renders_as_graphic(scene=scene, entry=None, shot=shot, filmed_by_operator=True)
        is False
    )


def _compile(visuals: dict[int, str] | None) -> str:
    package = CinematicPromptCompilationService().compile(
        scenes=[_scene(1)],
        shot_plan=_title_card_shot(),
        visual_continuity_bible=_bible(),
        production_semantic_brief=None,
        script_lock_hash="hash123",
        scene_visuals=visuals,
    )
    prompt = package.prompt_for_scene(1)
    assert prompt is not None

    return prompt.prompt_text


def test_without_a_visual_the_title_card_scene_may_print_its_narration() -> None:
    assert exact_text_for(_scene(1)) in _compile(None)


def test_with_a_visual_the_scene_is_filmed_and_prints_nothing() -> None:
    text = _compile({1: "A mud-brick room at night, a man hunched over papyrus"})

    assert exact_text_for(_scene(1)) not in text
    assert "A mud-brick room at night" in text
    assert "Do not show any text" in text


def test_the_scene_text_pass_no_longer_skips_a_scene_the_operator_described() -> None:
    job = _job(2)
    job.cinematic_shot_plan = _title_card_shot()
    service = SceneDetailService.__new__(SceneDetailService)

    assert SceneDetailService._is_graphic(job, job.scenes[0]) is True  # noqa: SLF001
    assert [s.scene_number for s in service.scenes_needing_detail(job)] == [2]

    job.scene_visual_plan = SceneVisualPlan(
        visuals=[
            SceneVisual(
                scene_number=1,
                text="A room at night",
                narration_key=narration_key(job.scenes[0].narration),
            )
        ]
    )

    assert SceneDetailService._is_graphic(job, job.scenes[0]) is False  # noqa: SLF001
    assert [s.scene_number for s in service.scenes_needing_detail(job)] == [1, 2]


def test_a_stale_visual_does_not_unmake_a_graphic() -> None:
    job = _job(2)
    job.cinematic_shot_plan = _title_card_shot()
    job.scene_visual_plan = SceneVisualPlan(
        visuals=[
            SceneVisual(scene_number=1, text="x", narration_key=narration_key("other"))
        ]
    )

    assert SceneDetailService._is_graphic(job, job.scenes[0]) is True  # noqa: SLF001
