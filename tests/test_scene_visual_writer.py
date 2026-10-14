"""
Claude writes the scene visuals (2026-10-14), as a third way in beside pasting a table and typing. Haiku 5.5
made it cheap (a rebuild costs cents), and a script imported as plain narration otherwise plays as a
documentary. The proposals are put in the scene boxes UNSAVED: a box the operator filled and a saved visual
are never touched, a scene Claude would show plainly stays empty, and a bad reply loses nothing.
"""

from __future__ import annotations

import logging

import pytest
from PySide6.QtWidgets import QComboBox, QVBoxLayout, QWidget

from src.models.scene import Scene
from src.models.scene_visual import SceneVisual, SceneVisualPlan, narration_key
from src.models.story_treatment import StoryTreatment
from src.models.suggestions import SuggestionStatus
from src.services.content_intelligence_pipeline import ContentIntelligencePipeline
from src.services.scene_visual_review_service import SceneVisualReviewService
from src.services.scene_visual_writer_service import (
    SceneVisualWriterService,
    VisualRange,
    _clean,
    default_range_for,
)
from tests.test_scene_detail import _job, _ScriptedLLM
from tests.test_suggestions import (
    _studio,
    _texts,
)
from tests.test_suggestions import (
    qapp as qapp,  # noqa: PLC0414 - fixture
)


def _service(llm: _ScriptedLLM, **kwargs) -> SceneVisualWriterService:  # type: ignore[no-untyped-def]
    return SceneVisualWriterService(llm_service=llm, **kwargs)  # type: ignore[arg-type]


def _reply(numbers: list[int], text: str = "A pale figure stands in a doorway") -> str:
    return "\n---\n".join(f"SCENE: {n}\nVISUAL: {text} {n}." for n in numbers)


# --------------------------------------------------------------------------------- range


@pytest.mark.parametrize(
    ("genre", "expected"),
    [
        ("genre.horror", VisualRange.CINEMATIC),
        ("genre.mystery", VisualRange.CINEMATIC),
        ("genre.medical", VisualRange.STORY_ONLY),
        ("genre.history", VisualRange.STORY_ONLY),
        ("genre.default", VisualRange.STORY_ONLY),
    ],
)
def test_the_default_range_follows_the_genre(genre: str, expected: VisualRange) -> None:
    assert default_range_for(genre) == expected


# -------------------------------------------------------------------------------- prompt


def test_the_prompt_carries_the_whole_script_but_asks_only_for_the_batch() -> None:
    job = _job(5)
    llm = _ScriptedLLM([_reply([2, 3])])

    _service(llm).write(job, visual_range=VisualRange.STORY_ONLY, scene_numbers=[2, 3])

    prompt = llm.requests[0].prompt
    assert all(f"{n}. Narration {n}." in prompt for n in range(1, 6))
    assert "Write the visual for scenes 2, 3 ONLY" in prompt


def test_the_range_rules_reach_the_prompt() -> None:
    job = _job(2)
    story, cinematic = _ScriptedLLM(["NONE"]), _ScriptedLLM(["NONE"])

    _service(story).write(job, visual_range=VisualRange.STORY_ONLY)
    _service(cinematic).write(job, visual_range=VisualRange.CINEMATIC)

    assert "STAY WITH THE STORY" in story.requests[0].prompt
    assert "Do not add a creature" in story.requests[0].prompt
    assert "CINEMATIC" in cinematic.requests[0].prompt
    assert "Suggest, do not show" in cinematic.requests[0].prompt
    assert "STAY WITH THE STORY" not in cinematic.requests[0].prompt


def test_the_prompt_carries_the_rules_the_clips_need() -> None:
    llm = _ScriptedLLM(["NONE"])

    _service(llm).write(_job(2), visual_range=VisualRange.CINEMATIC)

    prompt = llm.requests[0].prompt
    for rule in (
        "ONE place and ONE era",
        "no cut, match cut, montage, title card",
        "Never text, captions",
        "Non-graphic",
        "'same', 'as before'",
        "write NONE",
    ):
        assert rule in prompt, rule


def test_genre_treatment_known_people_and_an_accepted_opening_are_given() -> None:
    job = _job(3)
    job.genre_id = "genre.horror"
    job.story_treatment = StoryTreatment(
        hook_visual="A shape at the lamp's edge", hook_status=SuggestionStatus.ACCEPTED
    )
    llm = _ScriptedLLM(["NONE"])

    _service(llm).write(job, visual_range=VisualRange.CINEMATIC)

    prompt = llm.requests[0].prompt
    assert "Genre treatment:" in prompt and "NOT documentary" in prompt
    assert "The village (location)" in prompt
    assert (
        "approved this opening image for scene 1: A shape at the lamp's edge" in prompt
    )


def test_a_pending_opening_is_not_sent() -> None:
    job = _job(2)
    job.story_treatment = StoryTreatment(hook_visual="Pending image")
    llm = _ScriptedLLM(["NONE"])

    _service(llm).write(job, visual_range=VisualRange.STORY_ONLY)

    assert "Pending image" not in llm.requests[0].prompt


# --------------------------------------------------------------------------------- parse


def test_blocks_on_separate_lines_are_read() -> None:
    found = _service(_ScriptedLLM([_reply([1, 2])])).write(
        _job(3), visual_range=VisualRange.STORY_ONLY
    )

    assert found == {
        1: "A pale figure stands in a doorway 1.",
        2: "A pale figure stands in a doorway 2.",
    }


@pytest.mark.parametrize(
    "block",
    [
        "SCENE 1 VISUAL: A figure in a doorway.",
        "SCENE: 1 - VISUAL: A figure in a doorway.",
        "**SCENE 1** VISUAL: A figure in a doorway.",
        "**SCENE:** 1\n**VISUAL:** A figure in a doorway.",
    ],
)
def test_every_way_of_writing_a_block_is_read(block: str) -> None:
    found = _service(_ScriptedLLM([block])).write(
        _job(2), visual_range=VisualRange.STORY_ONLY
    )

    assert found == {1: "A figure in a doorway."}


def test_none_and_empty_visuals_leave_a_scene_out() -> None:
    reply = "SCENE: 1\nVISUAL: NONE\n---\nSCENE: 2\nVISUAL: -\n---\nSCENE: 3\nVISUAL: A jar rolls."

    found = _service(_ScriptedLLM([reply])).write(
        _job(3), visual_range=VisualRange.STORY_ONLY
    )

    assert found == {3: "A jar rolls."}


def test_a_whole_reply_of_none_gives_nothing() -> None:
    assert (
        _service(_ScriptedLLM(["NONE"])).write(
            _job(3), visual_range=VisualRange.STORY_ONLY
        )
        == {}
    )


def test_scenes_the_batch_did_not_ask_for_are_dropped() -> None:
    found = _service(_ScriptedLLM([_reply([1, 2, 9])])).write(
        _job(3), visual_range=VisualRange.STORY_ONLY, scene_numbers=[1]
    )

    assert list(found) == [1]


def test_editing_sentences_are_removed_from_a_visual() -> None:
    assert (
        _clean(
            "A pale shape stands at the door. Hard cut to black. One beat of silence."
        )
        == "A pale shape stands at the door. One beat of silence."
    )
    assert _clean("Montage of offering bowls.") == ""
    assert _clean("A title card fades in over the room.") == ""
    assert _clean("**A man** writes `fast`.") == "A man writes fast."


def test_a_very_long_visual_is_cut_at_a_word() -> None:
    cleaned = _clean("word " * 400)

    assert len(cleaned) <= 700 and not cleaned.endswith(" ")


def test_a_reply_that_gives_nothing_usable_is_logged(caplog) -> None:  # type: ignore[no-untyped-def]
    with caplog.at_level(logging.WARNING):
        found = _service(_ScriptedLLM(["Sure! Here are some ideas."])).write(
            _job(2), visual_range=VisualRange.STORY_ONLY
        )

    assert found == {}
    assert "nothing usable" in caplog.text


# ------------------------------------------------------------------------------ batching


def _scenes_job(count: int):  # type: ignore[no-untyped-def]
    job = _job(3)
    job.scenes = [
        Scene(
            scene_number=n,
            title=f"Scene {n}",
            narration=f"Narration {n}.",
            visual_prompt="v",
            estimated_duration_seconds=8,
        )
        for n in range(1, count + 1)
    ]

    return job


def test_one_failed_batch_keeps_the_others() -> None:
    job = _scenes_job(4)
    llm = _ScriptedLLM([_reply([1, 2]), None])

    found = _service(llm, batch_size=2).write(job, visual_range=VisualRange.STORY_ONLY)

    assert sorted(found) == [1, 2]


def test_every_batch_failing_raises_in_plain_words() -> None:
    with pytest.raises(RuntimeError, match="Writing the scene visuals failed"):
        _service(_ScriptedLLM([None])).write(
            _job(2), visual_range=VisualRange.STORY_ONLY
        )


def test_the_service_refuses_nonsense() -> None:
    with pytest.raises(ValueError, match="batch size"):
        _service(_ScriptedLLM([]), batch_size=0)

    with pytest.raises(ValueError, match="cannot be negative"):
        _service(_ScriptedLLM([]), estimated_cost_usd=-1)

    empty = _job(2)
    empty.scenes = []

    with pytest.raises(ValueError, match="planned scenes"):
        _service(_ScriptedLLM([])).write(empty, visual_range=VisualRange.STORY_ONLY)


# ------------------------------------------------------------------------------ pipeline


def _pipeline(llm: _ScriptedLLM) -> ContentIntelligencePipeline:
    pipeline = ContentIntelligencePipeline.__new__(ContentIntelligencePipeline)
    pipeline.scene_visual_writer_service = _service(llm)
    # the writer's output is polished by the review service (it only calls a model when a proposal
    # has a problem, and these proposals are clean)
    pipeline.scene_visual_review_service = SceneVisualReviewService(
        llm_service=llm  # type: ignore[arg-type]
    )

    return pipeline


def test_the_pipeline_returns_proposals_and_changes_nothing_on_the_job() -> None:
    job = _job(3)
    before = job.model_dump_json()

    found = _pipeline(_ScriptedLLM([_reply([1, 3])])).write_scene_visuals(
        job, visual_range=VisualRange.CINEMATIC, scene_numbers=[1, 3]
    )

    assert sorted(found) == [1, 3]
    assert job.model_dump_json() == before
    assert job.scene_visual_plan is None


def test_the_pipeline_needs_scenes() -> None:
    job = _job(2)
    job.scenes = []

    with pytest.raises(RuntimeError, match="planned scenes"):
        _pipeline(_ScriptedLLM([])).write_scene_visuals(
            job, visual_range=VisualRange.STORY_ONLY
        )


# ---------------------------------------------------------------------------------- panel

_ALIVE: list[QWidget] = []


def _panel(view, job) -> QWidget:  # type: ignore[no-untyped-def]
    holder = QWidget()
    _ALIVE.append(holder)
    layout = QVBoxLayout(holder)
    view._render_scene_visuals_panel(layout, job)  # noqa: SLF001

    return holder


def _stub_writer(view, proposals, calls):  # type: ignore[no-untyped-def]
    def write(job, *, visual_range, scene_numbers=None):  # type: ignore[no-untyped-def]
        calls.append((visual_range, list(scene_numbers or [])))

        return dict(proposals)

    view._content_intelligence_pipeline.write_scene_visuals = write  # type: ignore[method-assign]


def test_the_panel_offers_claude_next_to_pasting_and_typing(qapp) -> None:  # type: ignore[no-untyped-def]
    view, studio_job, _errors = _studio(_job(3))

    holder = _panel(view, studio_job)
    texts = _texts(holder)

    assert "Write visuals with Claude" in texts
    assert "Match to scenes" in texts and "Save visuals" in texts
    selects = holder.findChildren(QComboBox)
    assert [s.itemText(i) for s in selects for i in range(s.count())][:2] == [
        "Stay with the story - only what the script says",
        "Cinematic - add glimpses and atmosphere that serve the genre",
    ]


@pytest.mark.parametrize(
    ("genre", "expected"),
    [
        ("genre.horror", VisualRange.CINEMATIC),
        ("genre.medical", VisualRange.STORY_ONLY),
    ],
)
def test_the_range_starts_where_the_genre_points(qapp, genre, expected) -> None:  # type: ignore[no-untyped-def]
    view, studio_job, _errors = _studio(_job(3))
    studio_job.genre_id = genre
    _panel(view, studio_job)

    assert view._visual_range_select.currentData() == expected  # noqa: SLF001


def test_writing_fills_the_empty_boxes_unsaved_and_leaves_plain_scenes_empty(qapp) -> None:  # type: ignore[no-untyped-def]
    view, studio_job, errors = _studio(_job(3))
    calls: list = []
    _stub_writer(view, {1: "A figure in a doorway.", 3: "A jar rolls."}, calls)
    _panel(view, studio_job)

    view._handle_write_visuals()  # noqa: SLF001
    holder = _panel(view, studio_job)

    editors = view._visual_editors  # noqa: SLF001
    assert editors[1].toPlainText() == "A figure in a doorway."
    assert editors[2].toPlainText() == ""
    assert editors[3].toPlainText() == "A jar rolls."
    assert calls == [(default_range_for(studio_job.genre_id), [1, 2, 3])]
    assert studio_job.scene_visual_plan is None
    assert any(
        "Claude wrote 2 visual(s)" in t and "1 scene(s) were left empty" in t
        for t in _texts(holder)
    )
    assert errors == []


def test_a_filled_box_and_a_saved_visual_are_never_asked_for_or_overwritten(qapp) -> None:  # type: ignore[no-untyped-def]
    view, studio_job, _errors = _studio(_job(4))
    studio_job.scene_visual_plan = SceneVisualPlan(
        visuals=[
            SceneVisual(
                scene_number=2,
                text="Saved",
                narration_key=narration_key("Narration 2."),
            )
        ]
    )
    calls: list = []
    _stub_writer(
        view,
        {1: "New one", 2: "Overwrite attempt", 3: "New three", 4: "New four"},
        calls,
    )
    _panel(view, studio_job)
    view._visual_editors[1].setPlainText("Typed by hand")  # noqa: SLF001

    view._handle_write_visuals()  # noqa: SLF001
    _panel(view, studio_job)

    assert calls[0][1] == [3, 4]
    editors = view._visual_editors  # noqa: SLF001
    assert editors[1].toPlainText() == "Typed by hand"
    assert editors[2].toPlainText() == "Saved"
    assert editors[3].toPlainText() == "New three"
    assert editors[4].toPlainText() == "New four"


def test_a_box_filled_while_claude_was_writing_keeps_the_operators_text(qapp) -> None:  # type: ignore[no-untyped-def]
    view, studio_job, _errors = _studio(_job(2))
    _panel(view, studio_job)

    def write(job, *, visual_range, scene_numbers=None):  # type: ignore[no-untyped-def]
        view._visual_editors[1].setPlainText("Typed meanwhile")  # noqa: SLF001

        return {1: "Claude's version", 2: "Claude two"}

    view._content_intelligence_pipeline.write_scene_visuals = write  # type: ignore[method-assign]

    view._handle_write_visuals()  # noqa: SLF001
    _panel(view, studio_job)

    assert view._visual_editors[1].toPlainText() == "Typed meanwhile"  # noqa: SLF001
    assert view._visual_editors[2].toPlainText() == "Claude two"  # noqa: SLF001


def test_the_chosen_range_is_what_claude_is_told(qapp) -> None:  # type: ignore[no-untyped-def]
    view, studio_job, _errors = _studio(_job(2))
    studio_job.genre_id = "genre.medical"
    calls: list = []
    _stub_writer(view, {}, calls)
    _panel(view, studio_job)

    view._visual_range_select.setCurrentIndex(1)  # noqa: SLF001 - Cinematic
    view._handle_write_visuals()  # noqa: SLF001

    assert calls[0][0] == VisualRange.CINEMATIC


def test_when_every_scene_has_a_visual_nothing_is_asked(qapp) -> None:  # type: ignore[no-untyped-def]
    view, studio_job, _errors = _studio(_job(2))
    calls: list = []
    _stub_writer(view, {1: "x"}, calls)
    _panel(view, studio_job)
    for editor in view._visual_editors.values():  # noqa: SLF001
        editor.setPlainText("Already written")

    view._handle_write_visuals()  # noqa: SLF001
    texts = _texts(_panel(view, studio_job))

    assert calls == []
    assert any("Every scene already has a visual" in t for t in texts)


def test_a_failed_call_is_reported_and_changes_no_box(qapp) -> None:  # type: ignore[no-untyped-def]
    view, studio_job, errors = _studio(_job(2))
    _panel(view, studio_job)

    def write(job, *, visual_range, scene_numbers=None):  # type: ignore[no-untyped-def]
        raise RuntimeError("Writing the scene visuals failed: Provider unavailable.")

    view._content_intelligence_pipeline.write_scene_visuals = write  # type: ignore[method-assign]

    view._handle_write_visuals()  # noqa: SLF001
    _panel(view, studio_job)

    assert any("Could not write the scene visuals" in e for e in errors)
    assert all(
        e.toPlainText() == "" for e in view._visual_editors.values()
    )  # noqa: SLF001


def test_saving_after_claude_wrote_them_stores_them_as_the_operators_own(qapp) -> None:  # type: ignore[no-untyped-def]
    view, studio_job, _errors = _studio(_job(2))
    _stub_writer(view, {1: "A figure in a doorway."}, [])
    _panel(view, studio_job)

    view._handle_write_visuals()  # noqa: SLF001
    _panel(view, studio_job)
    view._handle_save_visuals(False)  # noqa: SLF001

    assert studio_job.current_scene_visuals == {1: "A figure in a doorway."}


# ------------------------------------------------------------------------------ messages


def test_visuals_removed_after_a_shot_plan_was_made_with_them_say_so(qapp) -> None:  # type: ignore[no-untyped-def]
    """Live, 2026-10-14: the operator removed every visual, then had Claude write new ones; the old
    warning said the plan predated 'these visuals' although none were saved."""

    from src.models.shot_planning import CinematicShotPlan

    view, studio_job, _errors = _studio(_job(2))
    studio_job.cinematic_shot_plan = CinematicShotPlan(
        script_lock_hash="hash123", visual_revision="old-revision"
    )
    studio_job.scene_visual_plan = None

    texts = _texts(_panel(view, studio_job))

    assert any(
        "made with visuals that have since been removed or changed" in t for t in texts
    )
    assert not any("made before these visuals" in t for t in texts)


def test_text_in_the_boxes_that_is_not_saved_is_flagged_until_it_is_saved(qapp) -> None:  # type: ignore[no-untyped-def]
    view, studio_job, _errors = _studio(_job(3))
    _stub_writer(view, {1: "A figure in a doorway.", 3: "A jar rolls."}, [])
    _panel(view, studio_job)
    assert not any("not saved yet" in t for t in _texts(_panel(view, studio_job)))

    view._handle_write_visuals()  # noqa: SLF001
    texts = _texts(_panel(view, studio_job))

    assert any(
        "scene(s) 1, 3 hold text that is not saved yet" in t.replace("box(es) of ", "")
        or ("1, 3" in t and "not saved yet" in t)
        for t in texts
    )

    view._handle_save_visuals(False)  # noqa: SLF001
    texts = _texts(_panel(view, studio_job))

    assert not any("hold text that is not saved yet" in t for t in texts)
