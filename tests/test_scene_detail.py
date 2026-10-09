"""
The detailed prompt pieces (Phase 2, 2026-10-09). Lake Nyos prompts were 380-500 characters of labels;
a clip generated from that has nothing to be faithful to. Two batched writing passes lift them:
`SceneDetailService` writes the scene-specific paragraph for each live-action scene, and
`IdentityDetailService` expands the thin place and character descriptions the bible generated. Both
write only what is missing or stale, never touch what the operator wrote, and a failed batch loses
only that batch.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.project_look import ProjectLook
from src.models.scene import Scene
from src.models.scene_detail import SceneDetail, SceneDetailPlan
from src.models.video_job import VideoJob
from src.models.visual_continuity import (
    CanonicalEntityIdentity,
    CanonicalEntityType,
    ClipContinuityEntry,
    VisualContinuityBible,
    VisualState,
)
from src.services.identity_detail_service import (
    THIN_BELOW_CHARACTERS,
    IdentityDetailService,
)
from src.services.scene_detail_service import SceneDetailService
from src.services.scene_detail_source import scene_detail_source_hash
from src.shared.llm.models import LLMCallResult, LLMCallStatus, LLMProvider
from src.shared.llm.request import LLMRequest
from tests.test_cinematic_prompt_compilation_service import _shot_plan

_LONG = (
    "A low, wide view across the village from the track: thatched huts with red earth "
    "walls fill the middle ground, banana trees frame the left edge and misty green hills "
    "sit behind. Flat grey light from above, damp ground, a slow push-in, still air and "
    "distant birdsong."
)


class _ScriptedLLM:
    """Answers each call from a queue; None fails that call."""

    def __init__(self, replies: list[str | None]) -> None:
        self._replies = list(replies)
        self.requests: list[LLMRequest] = []

    def generate(self, request, *, estimated_cost_usd=0.0, profile_ids=None):  # type: ignore[no-untyped-def]
        from src.services.llm.llm_service import LLMServiceResult

        self.requests.append(request)
        reply = self._replies.pop(0) if self._replies else None
        ok = reply is not None
        result = LLMCallResult(
            status=LLMCallStatus.SUCCESS if ok else LLMCallStatus.PROVIDER_ERROR,
            provider=LLMProvider.OPENAI,
            model="test-model",
            content=reply if ok else None,
            error_message=None if ok else "Provider unavailable.",
        )

        return LLMServiceResult(
            result=result,
            selected_profile_id="p" if ok else None,
            all_providers_failed=not ok,
        )


def _block(number: int, text: str = _LONG) -> str:
    return f"SCENE: {number}\nDETAIL: {text}"


def _job(scene_count: int = 3) -> VideoJob:
    job = VideoJob(
        project_name="Lake Nyos",
        channel_name="Channel",
        niche="documentary",
        topic="Lake Nyos",
    )
    job.scenes = [
        Scene(
            scene_number=n,
            title=f"Scene {n}",
            narration=f"Narration {n}.",
            visual_prompt=f"Visual {n}.",
            estimated_duration_seconds=8,
        )
        for n in range(1, scene_count + 1)
    ]
    job.cinematic_shot_plan = _shot_plan()
    job.visual_continuity_bible = VisualContinuityBible(
        script_lock_hash="hash123",
        identities=[
            CanonicalEntityIdentity(
                entity_type=CanonicalEntityType.LOCATION,
                name="The village",
                canonical_description="A hillside village of thatched huts.",
            )
        ],
        clip_entries=[
            ClipContinuityEntry(
                scene_number=n,
                incoming_state=VisualState(),
                shot_action=f"Shot {n}.",
                outgoing_state=VisualState(location="The village", lighting="Overcast"),
                entity_names=["The village"],
                on_screen_entity_names=["The village"],
            )
            for n in range(1, scene_count + 1)
        ],
    )

    return job


def _service(llm: _ScriptedLLM, **kwargs) -> SceneDetailService:  # type: ignore[no-untyped-def]
    return SceneDetailService(llm_service=llm, **kwargs)  # type: ignore[arg-type]


# ------------------------------------------------------------------------- model


def test_a_detail_cleans_its_text() -> None:
    detail = SceneDetail(scene_number=1, text="  A  wide view.  ", source_hash="h")

    assert detail.text == "A wide view"


def test_a_detail_cannot_be_empty_or_huge() -> None:
    with pytest.raises(ValidationError):
        SceneDetail(scene_number=1, text="", source_hash="h")

    with pytest.raises(ValidationError):
        SceneDetail(scene_number=1, text="x" * 1201, source_hash="h")


def test_the_plan_returns_a_detail_only_while_its_source_is_unchanged() -> None:
    plan = SceneDetailPlan(
        details=[SceneDetail(scene_number=2, text="A wide view", source_hash="abc")]
    )

    assert plan.current_text_for(2, "abc") == "A wide view"
    assert plan.current_text_for(2, "changed") == ""
    assert plan.current_text_for(3, "abc") == ""
    assert plan.detail_for(2) is not None and plan.detail_for(9) is None


# --------------------------------------------------------------------- the source


def test_the_source_hash_follows_the_narration_the_shot_and_the_setting() -> None:
    job = _job()
    scene = job.scenes[0]
    shot = job.cinematic_shot_plan.shot_for_scene(1)  # type: ignore[union-attr]
    entry = job.visual_continuity_bible.entry_for_scene(1)  # type: ignore[union-attr]
    base = scene_detail_source_hash(scene=scene, shot=shot, continuity=entry)

    assert base == scene_detail_source_hash(scene=scene, shot=shot, continuity=entry)

    scene.narration = "A different line."
    assert scene_detail_source_hash(scene=scene, shot=shot, continuity=entry) != base

    scene.narration = "Narration 1."
    entry.outgoing_state.location = "The quarry"
    assert scene_detail_source_hash(scene=scene, shot=shot, continuity=entry) != base


def test_the_project_look_is_not_part_of_the_source() -> None:
    job = _job()
    service = _service(_ScriptedLLM([]))
    before = service.source_hash(job, job.scenes[0])

    job.project_look = ProjectLook(lighting="A new lighting word")

    assert service.source_hash(job, job.scenes[0]) == before


# ------------------------------------------------------------------ writing scenes


def test_every_live_scene_gets_a_detail_from_one_batched_call() -> None:
    llm = _ScriptedLLM(["\n---\n".join(_block(n) for n in (1, 2, 3))])
    job = _job()

    plan = _service(llm).draft(job)

    assert [d.scene_number for d in plan.details] == [1, 2, 3]
    assert len(llm.requests) == 1
    assert plan.details[0].text.startswith("A low, wide view across the village")


def test_scenes_are_sent_in_batches() -> None:
    llm = _ScriptedLLM(
        [
            "\n---\n".join(_block(n) for n in (1, 2)),
            "\n---\n".join(_block(n) for n in (3, 4)),
            _block(5),
        ]
    )
    job = _job(5)

    plan = _service(llm, batch_size=2).draft(job)

    assert len(llm.requests) == 3
    assert len(plan.details) == 5


def test_a_graphic_scene_is_not_written() -> None:
    job = _job()
    job.visual_continuity_bible.clip_entries[1].outgoing_state = VisualState(  # type: ignore[union-attr]
        location="Map overlay of the region"
    )
    job.visual_continuity_bible.clip_entries[1].incoming_state = VisualState(  # type: ignore[union-attr]
        location="Map overlay of the region"
    )
    llm = _ScriptedLLM([_block(1) + "\n---\n" + _block(3)])

    plan = _service(llm).draft(job)

    assert [d.scene_number for d in plan.details] == [1, 3]
    assert "SCENE 2" not in llm.requests[0].prompt


def test_a_scene_with_a_current_detail_is_kept_without_a_call() -> None:
    job = _job()
    service = _service(_ScriptedLLM([]))
    job.scene_detail_plan = SceneDetailPlan(
        details=[
            SceneDetail(
                scene_number=n, text=_LONG, source_hash=service.source_hash(job, s)
            )
            for n, s in ((1, job.scenes[0]), (2, job.scenes[1]), (3, job.scenes[2]))
        ]
    )
    llm = _ScriptedLLM([])

    plan = _service(llm).draft(job)

    assert llm.requests == []
    assert [d.scene_number for d in plan.details] == [1, 2, 3]


def test_a_scene_whose_inputs_changed_is_written_again_and_the_rest_kept() -> None:
    job = _job()
    service = _service(_ScriptedLLM([]))
    old = "An old description of a scene that has since changed " * 3
    job.scene_detail_plan = SceneDetailPlan(
        details=[
            SceneDetail(
                scene_number=n, text=_LONG, source_hash=service.source_hash(job, s)
            )
            for n, s in ((1, job.scenes[0]), (2, job.scenes[1]), (3, job.scenes[2]))
        ]
    )
    job.scenes[1].narration = "The narration was rewritten."
    llm = _ScriptedLLM([_block(2, "New: " + _LONG)])

    plan = _service(llm).draft(job)

    assert len(llm.requests) == 1
    assert (
        "SCENE 2" in llm.requests[0].prompt and "SCENE 1" not in llm.requests[0].prompt
    )
    assert [d.scene_number for d in plan.details] == [1, 2, 3]
    assert plan.detail_for(2).text.startswith("New:")  # type: ignore[union-attr]
    assert old not in [d.text for d in plan.details]


def test_a_failed_batch_loses_only_that_batch() -> None:
    llm = _ScriptedLLM([None, "\n---\n".join(_block(n) for n in (3, 4))])
    job = _job(4)

    plan = _service(llm, batch_size=2).draft(job)

    assert [d.scene_number for d in plan.details] == [3, 4]


def test_every_batch_failing_raises_a_plain_error() -> None:
    llm = _ScriptedLLM([None, None])

    with pytest.raises(RuntimeError, match="Writing scene details failed"):
        _service(llm, batch_size=2).draft(_job(4))


def test_a_detail_too_short_to_use_or_for_an_unknown_scene_is_dropped() -> None:
    llm = _ScriptedLLM(
        ["\n---\n".join([_block(1, "A view."), _block(2), _block(99), "garbage"])]
    )

    plan = _service(llm).draft(_job())

    assert [d.scene_number for d in plan.details] == [2]


def test_markdown_around_the_labels_is_read() -> None:
    reply = f"**SCENE:** 1\n**DETAIL:** {_LONG}"

    plan = _service(_ScriptedLLM([reply])).draft(_job(1))

    assert [d.scene_number for d in plan.details] == [1]


def test_the_prompt_carries_the_scene_the_shot_the_identity_and_the_rules() -> None:
    llm = _ScriptedLLM([_block(1)])
    job = _job(1)
    job.project_look = ProjectLook(lighting="Overcast", setting="Highland village")

    _service(llm).draft(job)

    prompt = llm.requests[0].prompt
    assert "Narration: Narration 1." in prompt
    assert "Action: The captain surveys the horizon" in prompt
    assert "On screen - The village: A hillside village of thatched huts." in prompt
    assert "setting: Highland village" in prompt
    assert "ONE line" in prompt and "never the words 'same'" in prompt


def test_a_project_with_no_shot_plan_cannot_be_written() -> None:
    job = _job()
    job.cinematic_shot_plan = None

    with pytest.raises(ValueError, match="shot plan"):
        _service(_ScriptedLLM([])).draft(job)


def test_scenes_needing_detail_lists_the_live_scenes_without_a_current_one() -> None:
    job = _job()
    service = _service(_ScriptedLLM([]))
    assert [s.scene_number for s in service.scenes_needing_detail(job)] == [1, 2, 3]

    job.scene_detail_plan = SceneDetailPlan(
        details=[
            SceneDetail(
                scene_number=1,
                text=_LONG,
                source_hash=service.source_hash(job, job.scenes[0]),
            )
        ]
    )

    assert [s.scene_number for s in service.scenes_needing_detail(job)] == [2, 3]


# --------------------------------------------------------------- identity details


def _identity_job() -> VideoJob:
    job = _job()
    bible = job.visual_continuity_bible
    assert bible is not None
    bible.identities = [
        CanonicalEntityIdentity(
            entity_type=CanonicalEntityType.LOCATION,
            name="Lake Nyos",
            canonical_description="A crater lake.",
        ),
        CanonicalEntityIdentity(
            entity_type=CanonicalEntityType.LOCATION,
            name="The village",
            canonical_description="A hillside village of thatched huts.",
            is_manual=True,
        ),
        CanonicalEntityIdentity(
            entity_type=CanonicalEntityType.PERSON,
            name="Elder",
            canonical_description="x" * THIN_BELOW_CHARACTERS,
        ),
        CanonicalEntityIdentity(
            entity_type=CanonicalEntityType.LOCATION,
            name="Never shown",
            canonical_description="A cave.",
        ),
    ]
    for entry in bible.clip_entries:
        entry.on_screen_entity_names = ["Lake Nyos", "The village", "Elder"]

    return job


def _identity_service(llm: _ScriptedLLM) -> IdentityDetailService:
    return IdentityDetailService(llm_service=llm)  # type: ignore[arg-type]


def test_only_generated_short_descriptions_that_appear_on_screen_are_thin() -> None:
    thin = IdentityDetailService.thin_identities(_identity_job())

    assert [i.name for i in thin] == ["Lake Nyos"]  # not manual, not long, not unseen


def test_a_thin_description_is_expanded_and_the_rest_left_alone() -> None:
    job = _identity_job()
    reply = f"NAME: Lake Nyos\nDESCRIPTION: {_LONG}"
    llm = _ScriptedLLM([reply])

    expanded = _identity_service(llm).enrich(job)

    by_name = {i.name: i for i in job.visual_continuity_bible.identities}  # type: ignore[union-attr]
    assert expanded == ["Lake Nyos"]
    assert by_name["Lake Nyos"].canonical_description.startswith("A low, wide view")
    assert by_name["The village"].canonical_description == (
        "A hillside village of thatched huts."
    )
    assert by_name["Never shown"].canonical_description == "A cave."
    assert "CURRENT DESCRIPTION: A crater lake." in llm.requests[0].prompt


def test_nothing_is_called_when_nothing_is_thin() -> None:
    job = _identity_job()
    job.visual_continuity_bible.identities[0].canonical_description = "y" * 300  # type: ignore[union-attr]
    llm = _ScriptedLLM([])

    assert _identity_service(llm).enrich(job) == []
    assert llm.requests == []


def test_an_answer_that_adds_nothing_is_ignored() -> None:
    job = _identity_job()
    llm = _ScriptedLLM(
        [
            "NAME: Lake Nyos\nDESCRIPTION: A lake.\n---\nNAME: Ghost\nDESCRIPTION: "
            + _LONG
        ]
    )

    assert _identity_service(llm).enrich(job) == []
    assert job.visual_continuity_bible.identities[0].canonical_description == (  # type: ignore[union-attr]
        "A crater lake."
    )


def test_a_none_answer_changes_nothing() -> None:
    job = _identity_job()

    assert _identity_service(_ScriptedLLM(["NONE"])).enrich(job) == []


def test_a_failing_call_raises_a_plain_error() -> None:
    with pytest.raises(RuntimeError, match="Expanding the descriptions failed"):
        _identity_service(_ScriptedLLM([None])).enrich(_identity_job())


def test_a_very_long_expansion_is_cut_at_a_word_boundary() -> None:
    reply = "NAME: Lake Nyos\nDESCRIPTION: " + "word " * 400
    job = _identity_job()

    _identity_service(_ScriptedLLM([reply])).enrich(job)

    text = job.visual_continuity_bible.identities[0].canonical_description  # type: ignore[union-attr]
    assert 160 < len(text) <= 901


# ------------------------------------------------- the compiler uses a current detail


def _compile_with(plan: SceneDetailPlan | None, *, sub_clips: bool = False):  # type: ignore[no-untyped-def]
    from src.services.cinematic_prompt_compilation_service import (
        CinematicPromptCompilationService,
    )
    from tests.test_cinematic_prompt_compilation_service import _bible, _scene

    service = CinematicPromptCompilationService()
    shots = _shot_plan()
    bible = _bible()
    common = dict(
        shot_plan=shots,
        visual_continuity_bible=bible,
        production_semantic_brief=None,
        script_lock_hash="hash123",
        scene_detail_plan=plan,
    )

    if sub_clips:
        return [
            p.prompt_text
            for p in service.compile_sub_clip_prompts(
                scene=_scene(1), sub_clip_durations=[6.0, 6.0], **common  # type: ignore[arg-type]
            )
        ]

    package = service.compile(scenes=[_scene(1)], **common)  # type: ignore[arg-type]
    prompt = package.prompt_for_scene(1)
    assert prompt is not None

    return prompt.prompt_text


def _plan_for_scene_one(text: str = _LONG, *, hash_override: str | None = None):  # type: ignore[no-untyped-def]
    from tests.test_cinematic_prompt_compilation_service import _bible, _scene

    shots, bible = _shot_plan(), _bible()
    source = hash_override or scene_detail_source_hash(
        scene=_scene(1),
        shot=shots.shot_for_scene(1),
        continuity=bible.entry_for_scene(1),
    )

    return SceneDetailPlan(
        details=[SceneDetail(scene_number=1, text=text, source_hash=source)]
    )


def test_a_current_detail_is_in_the_prompt_between_composition_and_camera() -> None:
    text = _compile_with(_plan_for_scene_one())

    assert "Scene detail: A low, wide view across the village" in text
    assert (
        text.index("Composition:")
        < text.index("Scene detail:")
        < text.index("Lens/camera:")
    )


def test_a_stale_detail_is_left_out() -> None:
    text = _compile_with(_plan_for_scene_one(hash_override="not-the-current-source"))

    assert "Scene detail:" not in text


def test_no_plan_means_no_detail_sentence() -> None:
    assert "Scene detail:" not in _compile_with(None)


def test_every_sub_clip_of_a_split_scene_carries_the_detail() -> None:
    texts = _compile_with(_plan_for_scene_one(), sub_clips=True)

    assert len(texts) == 2
    assert all("Scene detail: A low, wide view" in t for t in texts)


def test_the_detail_makes_a_prompt_long_enough_for_the_completeness_check() -> None:
    from src.services.prompt_completeness_service import (
        MIN_LIVE_PROMPT_CHARACTERS,
        check_prompt_text,
    )

    thin = _compile_with(None)
    detailed = _compile_with(_plan_for_scene_one(_LONG * 2))

    assert len(detailed) > len(thin) + len(_LONG)
    assert len(detailed) >= MIN_LIVE_PROMPT_CHARACTERS
    assert not [f for f in check_prompt_text(detailed) if f.code.value == "too_short"]


# ---------------------------------------------------------------------- the pipeline


def _pipeline(replies: list[str | None], *, identity_replies: list[str | None] | None = None):  # type: ignore[no-untyped-def]
    from src.services.cinematic_prompt_compilation_service import (
        CinematicPromptCompilationService,
    )
    from src.services.content_intelligence_pipeline import ContentIntelligencePipeline

    pipeline = ContentIntelligencePipeline.__new__(ContentIntelligencePipeline)
    pipeline.scene_detail_service = SceneDetailService(
        llm_service=_ScriptedLLM(replies)  # type: ignore[arg-type]
    )
    pipeline.identity_detail_service = IdentityDetailService(
        llm_service=_ScriptedLLM(identity_replies or [])  # type: ignore[arg-type]
    )
    pipeline.cinematic_prompt_compilation_service = CinematicPromptCompilationService()

    class _Gate:
        def record_event(self, **kwargs):  # type: ignore[no-untyped-def]
            return None

    pipeline.approval_gate_service = _Gate()  # type: ignore[assignment]

    return pipeline


def test_the_stage_stores_the_plan_on_the_project() -> None:
    job = _job(2)
    pipeline = _pipeline(["\n---\n".join(_block(n) for n in (1, 2))])

    pipeline.run_scene_detail(job)

    assert job.scene_detail_plan is not None
    assert [d.scene_number for d in job.scene_detail_plan.details] == [1, 2]


def test_a_failing_stage_raises_but_the_unattended_wrapper_does_not() -> None:
    job = _job(2)

    with pytest.raises(RuntimeError, match="Writing scene details failed"):
        _pipeline([None]).run_scene_detail(job)

    assert job.scene_detail_plan is None  # still None, so a later run tries again

    result = _pipeline([None])._scene_detail_best_effort(job)  # noqa: SLF001

    assert result is job
    assert job.scene_detail_plan is None


def test_the_identity_stage_expands_a_thin_description() -> None:
    job = _identity_job()
    pipeline = _pipeline(
        [], identity_replies=[f"NAME: Lake Nyos\nDESCRIPTION: {_LONG}"]
    )

    pipeline.run_identity_detail(job)

    lake = next(
        i
        for i in job.visual_continuity_bible.identities  # type: ignore[union-attr]
        if i.name == "Lake Nyos"
    )
    assert lake.canonical_description.startswith("A low, wide view")


def test_a_project_saved_before_the_plan_existed_loads_without_one() -> None:
    data = _job(0).model_dump(mode="json")
    data.pop("scene_detail_plan")

    assert VideoJob.model_validate(data).scene_detail_plan is None


def test_the_plan_survives_saving_the_project() -> None:
    job = _job(0)
    job.scene_detail_plan = SceneDetailPlan(
        details=[SceneDetail(scene_number=1, text=_LONG, source_hash="h")]
    )

    reloaded = VideoJob.model_validate_json(job.model_dump_json())

    assert reloaded.scene_detail_plan is not None
    assert reloaded.scene_detail_plan.detail_for(1) is not None


# ---------------------------------------------------------------------------- the GUI

from tests.test_suggestions import (  # noqa: E402
    qapp as qapp,  # noqa: PLC0414 - fixture
)


def test_the_prompts_section_offers_the_detail_button_and_it_works(qapp) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from src.models.cinematic_prompt import (
        CinematicPromptPackage,
        ResolvedCinematicPrompt,
    )
    from tests.test_suggestions import _studio, _texts

    view, studio_job, errors = _studio(_job(2))
    studio_job.cinematic_shot_plan = _shot_plan()
    studio_job.cinematic_prompt_package = CinematicPromptPackage(
        script_lock_hash="hash123",
        prompts=[
            ResolvedCinematicPrompt(
                scene_number=1, script_lock_hash="hash123", prompt_text="x"
            )
        ],
    )
    holder = QWidget()
    layout = QVBoxLayout(holder)

    view._render_cinematic_prompt_section(layout, studio_job)  # noqa: SLF001

    assert "Write detailed scene text" in _texts(holder)

    class _Pipeline:
        def run_scene_detail(self, job):  # type: ignore[no-untyped-def]
            job.scene_detail_plan = SceneDetailPlan(
                details=[SceneDetail(scene_number=1, text=_LONG, source_hash="h")]
            )

            return job

    view._content_intelligence_pipeline = _Pipeline()  # type: ignore[assignment]  # noqa: SLF001

    view._handle_write_scene_details()  # noqa: SLF001

    assert errors == []
    assert studio_job.scene_detail_plan is not None
