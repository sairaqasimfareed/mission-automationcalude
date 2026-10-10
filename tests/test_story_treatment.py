"""
The story treatment (2026-10-10, live: Haunted wife): the video opened on a close-up of a letter and
nothing in it recurred to build dread. On request, one call proposes how the video OPENS and one person
or place that recurs as a brief glimpse; the operator accepts or discards each. The recurring presence
is an ordinary identity suggestion (the existing Accept flow); the opening image is a StoryTreatment
whose accepted text is given to the scene detail writer for scene 1. Nothing is applied on its own, and
nothing may add a person, event or object the script does not contain.
"""

from __future__ import annotations

import pytest

from src.models.scene_detail import SceneDetail, SceneDetailPlan
from src.models.story_treatment import StoryTreatment
from src.models.suggestions import IdentitySuggestion, SuggestionStatus
from src.models.video_job import VideoJob
from src.models.visual_continuity import CanonicalEntityType
from src.services.content_intelligence_pipeline import ContentIntelligencePipeline
from src.services.scene_detail_service import SceneDetailService
from src.services.story_treatment_service import StoryTreatmentService, _capped
from tests.test_scene_detail import _LONG, _block, _job, _ScriptedLLM
from tests.test_suggestions import (
    qapp as qapp,  # noqa: PLC0414 - fixture
)

_REPLY = (
    "HOOK: A pale woman's shape stands at the edge of lamplight, her back turned, before "
    "the camera drifts to the letter.\n"
    "MOTIF_NAME: The wife\n"
    "MOTIF_KIND: person\n"
    "MOTIF_DESCRIPTION: A slender woman in a pale linen sheath dress, face never fully seen, "
    "her outline softly lit from behind.\n"
    "MOTIF_SCENES: 1, 3, 5\n"
)


def _service(llm: _ScriptedLLM) -> StoryTreatmentService:
    return StoryTreatmentService(llm_service=llm)  # type: ignore[arg-type]


def _pipeline(llm: _ScriptedLLM) -> ContentIntelligencePipeline:
    pipeline = ContentIntelligencePipeline.__new__(ContentIntelligencePipeline)
    pipeline.story_treatment_service = _service(llm)
    pipeline.scene_detail_service = SceneDetailService(llm_service=llm)  # type: ignore[arg-type]
    return pipeline


# --------------------------------------------------------------------------- model


def test_the_accepted_hook_is_empty_until_accepted() -> None:
    treatment = StoryTreatment(hook_visual="A shape at the edge of lamplight")

    assert treatment.accepted_hook == ""

    treatment.hook_status = SuggestionStatus.ACCEPTED

    assert treatment.accepted_hook == "A shape at the edge of lamplight"


def test_a_treatment_needs_a_hook_and_cleans_its_text() -> None:
    with pytest.raises(ValueError):
        StoryTreatment(hook_visual="")

    assert StoryTreatment(hook_visual="  A  shape. ").hook_visual == "A shape."


def test_a_job_saved_before_treatments_existed_loads() -> None:
    job = VideoJob(project_name="P", channel_name="C", niche="n", topic="T")
    data = job.model_dump(mode="json")
    data.pop("story_treatment", None)

    assert VideoJob.model_validate(data).story_treatment is None


# ------------------------------------------------------------------------- service


def test_a_full_reply_gives_an_opening_and_a_presence() -> None:
    job = _job(6)
    proposal = _service(_ScriptedLLM([_REPLY])).propose(job)

    assert proposal.treatment is not None
    assert "back turned" in proposal.treatment.hook_visual
    assert proposal.treatment.hook_status == SuggestionStatus.PENDING
    assert proposal.treatment.motif_name == "The wife"
    assert proposal.motif is not None
    assert proposal.motif.kind == CanonicalEntityType.PERSON
    # recurs in at most a third of the 6 scenes, spread evenly, scene 1 (the hook) kept
    assert proposal.motif.scene_numbers == [1, 5]


def test_none_gives_nothing() -> None:
    proposal = _service(_ScriptedLLM(["HOOK: NONE\nMOTIF_NAME: NONE"])).propose(_job(6))

    assert proposal.treatment is None and proposal.motif is None


def test_a_hook_without_a_presence_is_kept() -> None:
    reply = "HOOK: The letter lies on warm sand.\nMOTIF_NAME: NONE\n"

    proposal = _service(_ScriptedLLM([reply])).propose(_job(6))

    assert proposal.treatment is not None and proposal.treatment.motif_name == ""
    assert proposal.motif is None


def test_a_presence_without_a_hook_is_kept() -> None:
    reply = _REPLY.replace(_REPLY.split("\n")[0], "HOOK: NONE")

    proposal = _service(_ScriptedLLM([reply])).propose(_job(6))

    assert proposal.treatment is None
    assert proposal.motif is not None


def test_a_presence_that_is_already_known_is_not_proposed_again() -> None:
    job = _job(6)
    job.identity_suggestions.append(
        IdentitySuggestion(
            name="The Wife",
            kind=CanonicalEntityType.PERSON,
            description="x",
            scene_numbers=[1, 2],
            status=SuggestionStatus.DISCARDED,
        )
    )

    proposal = _service(_ScriptedLLM([_REPLY])).propose(job)

    assert proposal.motif is None
    assert proposal.treatment is not None and proposal.treatment.motif_name == ""


def test_a_presence_needs_a_kind_a_description_and_two_scenes() -> None:
    for broken in (
        _REPLY.replace("MOTIF_KIND: person", "MOTIF_KIND: ghost"),
        _REPLY.replace("MOTIF_SCENES: 1, 3, 5", "MOTIF_SCENES: 4"),
        _REPLY.replace("MOTIF_SCENES: 1, 3, 5", "MOTIF_SCENES: 40, 41"),
        _REPLY.split("MOTIF_DESCRIPTION")[0] + "MOTIF_SCENES: 1, 3\n",
    ):
        proposal = _service(_ScriptedLLM([broken])).propose(_job(6))

        assert proposal.motif is None
        assert proposal.treatment is not None


def test_a_presence_stays_rare() -> None:
    assert _capped([1, 2, 3, 4, 5, 6], 6) == [1, 6]
    assert _capped([2, 9], 30) == [2, 9]
    assert _capped([1, 2, 3], 3) == [1, 3]

    many = _capped(list(range(1, 31)), 30)

    assert len(many) == 10 and many[0] == 1 and many[-1] == 30


def test_the_prompt_forbids_invention_and_carries_genre_and_known_people() -> None:
    llm = _ScriptedLLM([_REPLY])
    job = _job(6)
    job.genre_id = "genre.horror"

    _service(llm).propose(job)

    prompt = llm.requests[0].prompt

    assert "add no character, event or object it does not contain" in prompt
    assert "Genre treatment" in prompt
    assert "The village (location)" in prompt


def test_a_failed_call_raises_and_no_scenes_is_refused() -> None:
    with pytest.raises(RuntimeError, match="Proposing a treatment failed"):
        _service(_ScriptedLLM([None])).propose(_job(3))

    empty = _job(3)
    empty.scenes = []

    with pytest.raises(ValueError, match="planned scenes"):
        _service(_ScriptedLLM([_REPLY])).propose(empty)


# ------------------------------------------------------------------------ pipeline


def test_proposing_applies_nothing_but_keeps_both_proposals() -> None:
    job = _job(6)
    pipeline = _pipeline(_ScriptedLLM([_REPLY]))

    pipeline.run_story_treatment(job)

    assert job.story_treatment is not None
    assert job.story_treatment.hook_status == SuggestionStatus.PENDING
    assert job.story_treatment.accepted_hook == ""
    pending = [s for s in job.identity_suggestions if s.name == "The wife"]
    assert len(pending) == 1 and pending[0].status == SuggestionStatus.PENDING
    assert [i.name for i in job.visual_continuity_bible.identities] == ["The village"]  # type: ignore[union-attr]


def test_an_accepted_opening_cannot_be_replaced_by_asking_again() -> None:
    job = _job(6)
    job.story_treatment = StoryTreatment(
        hook_visual="Kept", hook_status=SuggestionStatus.ACCEPTED
    )
    pipeline = _pipeline(_ScriptedLLM([_REPLY]))

    with pytest.raises(RuntimeError, match="already accepted"):
        pipeline.run_story_treatment(job)

    assert job.story_treatment.hook_visual == "Kept"


def test_a_discarded_opening_can_be_asked_for_again() -> None:
    job = _job(6)
    job.story_treatment = StoryTreatment(
        hook_visual="Old", hook_status=SuggestionStatus.DISCARDED
    )
    pipeline = _pipeline(_ScriptedLLM([_REPLY]))

    pipeline.run_story_treatment(job)

    assert job.story_treatment.hook_status == SuggestionStatus.PENDING
    assert "back turned" in job.story_treatment.hook_visual


def test_proposing_needs_a_bible_and_scenes() -> None:
    pipeline = _pipeline(_ScriptedLLM([_REPLY]))
    no_bible = _job(3)
    no_bible.visual_continuity_bible = None

    with pytest.raises(RuntimeError, match="continuity bible"):
        pipeline.run_story_treatment(no_bible)

    no_scenes = _job(3)
    no_scenes.scenes = []

    with pytest.raises(RuntimeError, match="planned scenes"):
        pipeline.run_story_treatment(no_scenes)


def test_accepting_the_opening_rewrites_scene_one_around_it() -> None:
    job = _job(3)
    job.story_treatment = StoryTreatment(hook_visual="A shape at the lamp's edge")
    stale = SceneDetailPlan(
        details=[
            SceneDetail(scene_number=n, text=_LONG, source_hash="h") for n in (1, 2, 3)
        ]
    )
    job.scene_detail_plan = stale
    llm = _ScriptedLLM([_block(1, _LONG + " A pale shape stands in the lamplight.")])
    pipeline = _pipeline(llm)
    from src.services.scene_detail_source import scene_detail_source_hash

    # scenes 2 and 3 hold text that is still current, so only scene 1 needs writing
    for detail in stale.details:
        scene = next(s for s in job.scenes if s.scene_number == detail.scene_number)
        detail.source_hash = scene_detail_source_hash(
            scene=scene,
            shot=job.cinematic_shot_plan.shot_for_scene(scene.scene_number),  # type: ignore[union-attr]
            continuity=job.visual_continuity_bible.entry_for_scene(scene.scene_number),  # type: ignore[union-attr]
        )

    pipeline.accept_story_hook(job)

    assert job.story_treatment.hook_status == SuggestionStatus.ACCEPTED
    # one call, for scene 1 only: scenes 2 and 3 kept their current text
    assert len(llm.requests) == 1
    assert "Opening image the operator approved" in llm.requests[0].prompt
    assert "A shape at the lamp's edge" in llm.requests[0].prompt
    assert "SCENE 2" not in llm.requests[0].prompt
    assert job.scene_detail_plan is not None
    first = job.scene_detail_plan.detail_for(1)
    assert first is not None and "pale shape" in first.text
    assert job.scene_detail_plan.detail_for(2) is not None


def test_accepting_with_nothing_pending_is_refused() -> None:
    pipeline = _pipeline(_ScriptedLLM([]))

    with pytest.raises(RuntimeError, match="no proposed opening"):
        pipeline.accept_story_hook(_job(3))

    done = _job(3)
    done.story_treatment = StoryTreatment(
        hook_visual="x", hook_status=SuggestionStatus.ACCEPTED
    )

    with pytest.raises(RuntimeError, match="no proposed opening"):
        pipeline.accept_story_hook(done)


# --------------------------------------------------------------------- detail writer


def test_only_an_accepted_opening_reaches_the_scene_one_prompt() -> None:
    job = _job(3)
    job.story_treatment = StoryTreatment(hook_visual="A shape at the lamp's edge")

    pending = SceneDetailService._build_prompt(job, job.scenes)  # noqa: SLF001

    assert "Opening image" not in pending

    job.story_treatment.hook_status = SuggestionStatus.ACCEPTED
    accepted = SceneDetailService._build_prompt(job, job.scenes)  # noqa: SLF001

    assert accepted.count("Opening image the operator approved") == 1
    first, second = accepted.split("SCENE 2")[0], accepted.split("SCENE 2")[1]
    assert "Opening image" in first and "Opening image" not in second


# ------------------------------------------------------------------------------ GUI


def test_the_studio_offers_the_treatment_and_accept_discard(qapp) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from tests.test_suggestions import _studio, _texts

    view, studio_job, errors = _studio(_job(3))
    holder = QWidget()
    layout = QVBoxLayout(holder)

    view._render_story_treatment(layout, studio_job)  # noqa: SLF001

    assert "Suggest an opening and a recurring presence" in _texts(holder)

    studio_job.story_treatment = StoryTreatment(hook_visual="A shape at the lamp")
    holder = QWidget()
    layout = QVBoxLayout(holder)
    view._render_story_treatment(layout, studio_job)  # noqa: SLF001
    texts = _texts(holder)

    assert any("Proposed opening image: A shape at the lamp" in t for t in texts)
    assert "Accept opening image" in texts and "Discard" in texts
    assert "Suggest an opening and a recurring presence" not in texts

    view._handle_discard_story_hook()  # noqa: SLF001

    assert studio_job.story_treatment.hook_status == SuggestionStatus.DISCARDED
    holder = QWidget()
    layout = QVBoxLayout(holder)
    view._render_story_treatment(layout, studio_job)  # noqa: SLF001
    assert "Suggest an opening and a recurring presence" in _texts(holder)

    studio_job.story_treatment = StoryTreatment(
        hook_visual="Kept", hook_status=SuggestionStatus.ACCEPTED
    )
    holder = QWidget()
    layout = QVBoxLayout(holder)
    view._render_story_treatment(layout, studio_job)  # noqa: SLF001
    texts = _texts(holder)

    assert any("Opening image (accepted): Kept" in t for t in texts)
    assert "Suggest an opening and a recurring presence" not in texts
    assert errors == []


def test_the_handlers_do_not_crash_without_a_prerequisite(qapp) -> None:  # type: ignore[no-untyped-def]
    from tests.test_suggestions import _studio

    view, studio_job, _errors = _studio(_job(3))
    studio_job.visual_continuity_bible = None

    view._handle_suggest_story_treatment()  # noqa: SLF001 - reports the missing bible
    view._handle_accept_story_hook()  # noqa: SLF001 - nothing pending
    view._handle_discard_story_hook()  # noqa: SLF001 - no treatment

    assert studio_job.story_treatment is None
