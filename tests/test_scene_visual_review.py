"""
Check and improve visuals (2026-10-14). Found by comparing two sets of visuals for one project: a table written
outside the app had the better ideas but editing instructions a clip cannot do ("Hard cut to black",
"Montage", "Match cut", a title card), scenes holding several beats, and references to other scenes; the set
Claude wrote in the app was renderable but repeated one effect in three scenes and ran long. The check is
deterministic and free; one short call rewrites only the flagged scenes, into the boxes, unsaved and undoable.
The writer runs the same check on its own output. Every text below is taken from those two real sets.
"""

from __future__ import annotations

import logging

import pytest
from PySide6.QtWidgets import QVBoxLayout, QWidget

from src.services.content_intelligence_pipeline import ContentIntelligencePipeline
from src.services.scene_visual_review_service import (
    MAX_WORDS,
    SceneVisualReviewService,
    VisualIssueKind,
)
from src.services.scene_visual_writer_service import (
    SceneVisualWriterService,
    VisualRange,
)
from tests.test_scene_detail import _job, _ScriptedLLM
from tests.test_suggestions import (
    _studio,
    _texts,
)
from tests.test_suggestions import (
    qapp as qapp,  # noqa: PLC0414 - fixture
)

K = VisualIssueKind


def _kinds(visuals: dict[int, str]) -> dict[int, set[VisualIssueKind]]:
    return {
        number: {issue.kind for issue in issues}
        for number, issues in SceneVisualReviewService.check(visuals).items()
    }


# ----------------------------------------------------------------------------- check


def test_a_clean_visual_has_no_problems_and_an_empty_one_is_skipped() -> None:
    clean = (
        "Extreme close-up: a reed pen scratching black hieratic script onto papyrus by oil-lamp "
        "light. The hand is trembling."
    )

    assert _kinds({1: clean, 2: "   "}) == {}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hard cut to black. One beat of silence.", {K.EDITING_WORDS}),
        (
            "Montage: offering bowls left at tomb doors; painted eyes on a coffin lid.",
            {K.EDITING_WORDS},
        ),
        (
            "A figure stands, out of focus, then the shot cuts away before it sharpens.",
            {K.EDITING_WORDS},
        ),
        (
            "In the dark, the faint outline of a face for a fraction of a second. Cut to black.",
            {K.EDITING_WORDS},
        ),
        (
            "A pale hand-shaped blur hangs at the edge while the scene fades to black.",
            {K.EDITING_WORDS},
        ),
        (
            "Wide room. A title card fades in over it.",
            {K.EDITING_WORDS, K.TEXT_IN_PICTURE},
        ),
        ("A caption reads the year over the sunlit wall.", {K.TEXT_IN_PICTURE}),
        (
            "Match cut: the same papyrus, now brittle and brown, under glass.",
            {K.EDITING_WORDS, K.OTHER_SCENE},
        ),
        (
            "Back in ancient Egypt: the room from the opening, now empty.",
            {K.OTHER_SCENE},
        ),
        (
            "The linen over it slowly dents again, as if someone lay down.",
            {K.OTHER_SCENE},
        ),
    ],
)
def test_each_problem_in_the_pasted_set_is_found(
    text: str, expected: set[VisualIssueKind]
) -> None:
    assert _kinds({7: text}) == {7: expected}


def test_scene_two_of_the_pasted_set_has_several_problems_at_once() -> None:
    merged = (
        "Slow pull back: a mud-brick room at night, a man hunched over the papyrus, the Nile dark "
        "through a small window. Title card fades in: Egypt, over 3,000 years ago. Then His face, half "
        "lit: not grief, but fear. His eyes keep flicking to the dark doorway behind him."
    )

    kinds = _kinds({2: merged})[2]

    assert {K.EDITING_WORDS, K.TEXT_IN_PICTURE, K.SEVERAL_MOMENTS} <= kinds


def test_a_then_that_joins_two_images_is_several_moments() -> None:
    text = "A water jar tips and rolls across the floor. Then He jerks around."

    assert _kinds({9: text}) == {9: {K.SEVERAL_MOMENTS}}


def test_four_sentences_are_several_moments_and_three_are_not() -> None:
    three = "A man sleeps. The linen dents. His eyes open."
    four = three + " Nobody is there."

    assert _kinds({1: three}) == {}
    assert K.SEVERAL_MOMENTS in _kinds({1: four})[1]


def test_a_visual_over_the_word_limit_is_too_long() -> None:
    long_text = " ".join(["word"] * (MAX_WORDS + 1)) + "."
    issues = SceneVisualReviewService.check({18: long_text})[18]

    assert [i.kind for i in issues] == [K.TOO_LONG]
    assert str(MAX_WORDS + 1) in issues[0].describe()
    assert (
        SceneVisualReviewService.check({18: " ".join(["word"] * MAX_WORDS) + "."}) == {}
    )


def test_an_effect_used_in_three_scenes_flags_only_the_third_and_later() -> None:
    visuals = {
        4: "The reed mat dents inward slowly, as though pressed from above.",
        9: "A woven mat slides slowly across the floor by itself.",
        17: "The woven reeds of the mat lift and settle quietly.",
        18: "The lamp flame leans sideways, then rights itself.",
    }

    flagged = SceneVisualReviewService.check(visuals)

    assert list(flagged) == [17]
    assert flagged[17][0].kind == K.REPEATED_EFFECT and flagged[17][0].detail == "mat"


def test_two_scenes_with_the_same_effect_are_allowed() -> None:
    visuals = {
        1: "The mat dents inward slowly.",
        2: "A mat slides across the floor.",
    }

    assert SceneVisualReviewService.check(visuals) == {}


def test_an_object_that_only_sits_there_is_not_an_effect() -> None:
    visuals = {
        n: "A reed mat lies on the packed earth floor in lamplight."
        for n in (1, 2, 3, 4)
    }

    assert SceneVisualReviewService.check(visuals) == {}


# --------------------------------------------------------------------------- improve


def _review(llm: _ScriptedLLM) -> SceneVisualReviewService:
    return SceneVisualReviewService(llm_service=llm)  # type: ignore[arg-type]


def test_improve_sends_only_the_flagged_scenes_with_their_problems() -> None:
    job = _job(4)
    visuals = {
        1: "A man writes by lamplight.",
        2: "Hard cut to black. One beat of silence.",
        3: "The same room again, empty.",
        4: "A jar rolls across a floor.",
    }
    flagged = SceneVisualReviewService.check(visuals)
    llm = _ScriptedLLM(
        [
            "SCENE: 2\nVISUAL: Near-total darkness with one faint ember.\n---\nSCENE: 3\nVISUAL: An empty mud-brick room, the reed pen on the floor."
        ]
    )

    result = _review(llm).improve(job, visuals, flagged)

    prompt = llm.requests[0].prompt
    assert result == {
        2: "Near-total darkness with one faint ember.",
        3: "An empty mud-brick room, the reed pen on the floor.",
    }
    assert (
        "SCENE 2 - narration: Narration 2." in prompt
        and "SCENE 3 - narration" in prompt
    )
    assert "SCENE 1 - narration" not in prompt and "SCENE 4 - narration" not in prompt
    assert "CURRENT: Hard cut to black. One beat of silence." in prompt
    assert "PROBLEMS: editing words" in prompt and "refers to another scene" in prompt
    assert "place: The village" in prompt


def test_the_other_scenes_are_shown_briefly_so_effects_are_not_repeated() -> None:
    job = _job(3)
    visuals = {
        1: "A man writes by lamplight at a low wooden table in a mud-brick room tonight.",
        2: "Hard cut to black.",
    }
    llm = _ScriptedLLM(["NONE"])

    _review(llm).improve(job, visuals, SceneVisualReviewService.check(visuals))

    prompt = llm.requests[0].prompt
    assert "do not repeat their effects or images" in prompt
    assert (
        "1. A man writes by lamplight at a low wooden table in a mud-brick room"
        in prompt
    )
    assert "tonight" not in prompt  # cut to the first 14 words


def test_the_rewrite_rules_reach_the_prompt() -> None:
    job = _job(2)
    visuals = {1: "Montage of bowls."}
    llm = _ScriptedLLM(["NONE"])

    _review(llm).improve(job, visuals, SceneVisualReviewService.check(visuals))

    prompt = llm.requests[0].prompt
    for rule in (
        "ONE continuous moment of a single clip",
        "keep the strongest one",
        "At most 40 words",
        "near-total darkness with one faint detail, or NONE",
        "Never text, captions",
        "no 'same', 'again', 'as before', 'from the opening'",
        "give this scene a DIFFERENT effect",
    ):
        assert rule in prompt, rule


def test_a_reply_for_a_scene_that_was_not_flagged_is_dropped_and_none_leaves_it_alone() -> (
    None
):
    job = _job(3)
    visuals = {1: "Clean visual of a lamp.", 2: "Hard cut to black."}
    llm = _ScriptedLLM(
        ["SCENE: 1\nVISUAL: Sneaky rewrite.\n---\nSCENE: 2\nVISUAL: NONE"]
    )

    result = _review(llm).improve(job, visuals, SceneVisualReviewService.check(visuals))

    assert result == {}


def test_improve_with_nothing_flagged_makes_no_call() -> None:
    llm = _ScriptedLLM([])

    assert _review(llm).improve(_job(2), {1: "A man writes."}, {}) == {}
    assert llm.requests == []


def test_a_failed_call_raises_in_plain_words() -> None:
    visuals = {1: "Hard cut to black."}

    with pytest.raises(RuntimeError, match="Improving the scene visuals failed"):
        _review(_ScriptedLLM([None])).improve(
            _job(2), visuals, SceneVisualReviewService.check(visuals)
        )


def test_the_cost_cannot_be_negative() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        SceneVisualReviewService(llm_service=_ScriptedLLM([]), estimated_cost_usd=-1)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- pipeline


def _pipeline(
    writer_llm: _ScriptedLLM, review_llm: _ScriptedLLM | None = None
) -> ContentIntelligencePipeline:
    pipeline = ContentIntelligencePipeline.__new__(ContentIntelligencePipeline)
    pipeline.scene_visual_writer_service = SceneVisualWriterService(llm_service=writer_llm)  # type: ignore[arg-type]
    pipeline.scene_visual_review_service = SceneVisualReviewService(
        llm_service=review_llm or writer_llm  # type: ignore[arg-type]
    )

    return pipeline


def test_the_pipeline_checks_without_a_call_and_improves_only_when_something_is_flagged() -> (
    None
):
    llm = _ScriptedLLM(["SCENE: 1\nVISUAL: Near-total darkness."])
    pipeline = _pipeline(llm)

    assert pipeline.check_scene_visuals({1: "A man writes."}) == {}
    assert pipeline.improve_scene_visuals(_job(2), {1: "A man writes."}) == ({}, {})
    assert llm.requests == []

    rewritten, flagged = pipeline.improve_scene_visuals(
        _job(2), {1: "Hard cut to black."}
    )

    assert rewritten == {1: "Near-total darkness."}
    assert list(flagged) == [1]
    assert len(llm.requests) == 1


def test_a_written_visual_with_a_problem_is_polished_before_it_is_shown() -> None:
    too_long = " ".join(["detail"] * (MAX_WORDS + 5)) + "."
    writer_reply = f"SCENE: 1\nVISUAL: {too_long}\n---\nSCENE: 2\nVISUAL: A jar rolls across the floor."
    writer, review = _ScriptedLLM([writer_reply]), _ScriptedLLM(
        ["SCENE: 1\nVISUAL: A shorter image of a lamp."]
    )

    found = _pipeline(writer, review).write_scene_visuals(
        _job(3), visual_range=VisualRange.STORY_ONLY
    )

    assert found == {
        1: "A shorter image of a lamp.",
        2: "A jar rolls across the floor.",
    }
    assert len(writer.requests) == 1 and len(review.requests) == 1


def test_a_clean_written_set_costs_no_second_call() -> None:
    writer = _ScriptedLLM(["SCENE: 1\nVISUAL: A jar rolls across the floor."])
    review = _ScriptedLLM([])

    found = _pipeline(writer, review).write_scene_visuals(
        _job(2), visual_range=VisualRange.STORY_ONLY
    )

    assert found == {1: "A jar rolls across the floor."}
    assert review.requests == []


def test_a_failed_polish_keeps_the_proposals_as_written(caplog) -> None:  # type: ignore[no-untyped-def]
    too_long = " ".join(["detail"] * (MAX_WORDS + 5)) + "."
    writer = _ScriptedLLM([f"SCENE: 1\nVISUAL: {too_long}"])
    review = _ScriptedLLM([None])

    with caplog.at_level(logging.WARNING):
        found = _pipeline(writer, review).write_scene_visuals(
            _job(2), visual_range=VisualRange.STORY_ONLY
        )

    assert list(found) == [1] and found[1].startswith("detail")
    assert "Polishing the written visuals failed" in caplog.text


# ----------------------------------------------------------------------- writer prompt


def test_the_writer_prompt_has_examples_a_hook_rule_and_an_effect_limit() -> None:
    llm = _ScriptedLLM(["NONE"])

    SceneVisualWriterService(llm_service=llm).write(_job(3), visual_range=VisualRange.CINEMATIC)  # type: ignore[arg-type]

    prompt = llm.requests[0].prompt
    assert "STRONG: A ceiling fan slows to a stop" in prompt
    assert (
        "WEAK: A dark room where nothing happens." in prompt
        and "WEAK: Hard cut to black." in prompt
    )
    assert (
        "Scene 1 is the OPENING: make it the most arresting, specific image" in prompt
    )
    assert "Scene 3 is the LAST: land the story's final beat" in prompt
    assert "may be used in more than two scenes" in prompt


def test_the_examples_lend_the_story_no_props() -> None:
    from src.services.scene_visual_writer_service import _EXAMPLES

    for prop in ("papyrus", "lamp", "jar", "reed", "tomb", "egypt", "linen"):
        assert prop not in _EXAMPLES.lower(), prop


# ------------------------------------------------------------------------------ panel

_ALIVE: list[QWidget] = []


def _panel(view, job) -> QWidget:  # type: ignore[no-untyped-def]
    holder = QWidget()
    _ALIVE.append(holder)
    layout = QVBoxLayout(holder)
    view._render_scene_visuals_panel(layout, job)  # noqa: SLF001

    return holder


def test_the_panel_offers_check_and_improve(qapp) -> None:  # type: ignore[no-untyped-def]
    view, studio_job, _errors = _studio(_job(3))

    texts = _texts(_panel(view, studio_job))

    assert "Check and improve visuals" in texts
    assert "Undo the improvements" not in texts


def test_with_no_visuals_it_says_so_and_calls_nothing(qapp) -> None:  # type: ignore[no-untyped-def]
    view, studio_job, _errors = _studio(_job(2))
    _panel(view, studio_job)

    view._handle_improve_visuals()  # noqa: SLF001
    texts = _texts(_panel(view, studio_job))

    assert any("no visuals to check yet" in t for t in texts)


def test_clean_visuals_report_no_problems_and_cost_nothing(qapp) -> None:  # type: ignore[no-untyped-def]
    view, studio_job, _errors = _studio(_job(2))
    calls: list = []
    view._content_intelligence_pipeline.improve_scene_visuals = (  # type: ignore[method-assign]
        lambda job, visuals: calls.append(1) or ({}, {})
    )
    _panel(view, studio_job)
    view._visual_editors[1].setPlainText(
        "A jar rolls across the floor."
    )  # noqa: SLF001

    view._handle_improve_visuals()  # noqa: SLF001
    texts = _texts(_panel(view, studio_job))

    assert calls == []
    assert any("Checked 1 visual(s): no problems found" in t for t in texts)


def _stub_improve(view, rewritten):  # type: ignore[no-untyped-def]
    seen: list = []

    def improve(job, visuals):  # type: ignore[no-untyped-def]
        seen.append(dict(visuals))

        return dict(rewritten), {}

    view._content_intelligence_pipeline.improve_scene_visuals = improve  # type: ignore[method-assign]

    return seen


def test_flagged_scenes_are_rewritten_into_the_boxes_unsaved_and_can_be_undone(qapp) -> None:  # type: ignore[no-untyped-def]
    view, studio_job, errors = _studio(_job(3))
    seen = _stub_improve(view, {2: "Near-total darkness with one faint ember."})
    _panel(view, studio_job)
    view._visual_editors[1].setPlainText(
        "A jar rolls across the floor."
    )  # noqa: SLF001
    view._visual_editors[2].setPlainText("Hard cut to black.")  # noqa: SLF001

    view._handle_improve_visuals()  # noqa: SLF001
    holder = _panel(view, studio_job)
    texts = _texts(holder)

    assert seen == [{1: "A jar rolls across the floor.", 2: "Hard cut to black."}]
    assert (
        view._visual_editors[1].toPlainText() == "A jar rolls across the floor."
    )  # noqa: SLF001
    assert (
        view._visual_editors[2].toPlainText()
        == "Near-total darkness with one faint ember."
    )  # noqa: SLF001
    assert any(
        "1 had problems (editing words)" in t and "rewrote 1 scene(s) (2)" in t
        for t in texts
    )
    assert "Undo the improvements" in texts
    assert studio_job.scene_visual_plan is None

    view._handle_undo_improvements()  # noqa: SLF001
    texts = _texts(_panel(view, studio_job))

    assert view._visual_editors[2].toPlainText() == "Hard cut to black."  # noqa: SLF001
    assert "Undo the improvements" not in texts
    assert any("Brought back the original visuals of scene(s) 2" in t for t in texts)
    assert errors == []


def test_a_box_edited_while_claude_worked_is_left_alone(qapp) -> None:  # type: ignore[no-untyped-def]
    view, studio_job, _errors = _studio(_job(2))
    _panel(view, studio_job)
    view._visual_editors[1].setPlainText("Hard cut to black.")  # noqa: SLF001

    def improve(job, visuals):  # type: ignore[no-untyped-def]
        view._visual_editors[1].setPlainText("Typed meanwhile")  # noqa: SLF001

        return {1: "Claude's rewrite."}, {}

    view._content_intelligence_pipeline.improve_scene_visuals = improve  # type: ignore[method-assign]

    view._handle_improve_visuals()  # noqa: SLF001
    _panel(view, studio_job)

    assert view._visual_editors[1].toPlainText() == "Typed meanwhile"  # noqa: SLF001


def test_a_flagged_scene_claude_could_not_fix_is_named(qapp) -> None:  # type: ignore[no-untyped-def]
    view, studio_job, _errors = _studio(_job(3))
    _stub_improve(view, {2: "Near-total darkness."})
    _panel(view, studio_job)
    view._visual_editors[2].setPlainText("Hard cut to black.")  # noqa: SLF001
    view._visual_editors[3].setPlainText("Montage of bowls.")  # noqa: SLF001

    view._handle_improve_visuals()  # noqa: SLF001
    texts = _texts(_panel(view, studio_job))

    assert any("Scene(s) 3 still have problems - edit them by hand" in t for t in texts)


def test_a_failed_call_is_reported_and_changes_no_box(qapp) -> None:  # type: ignore[no-untyped-def]
    view, studio_job, errors = _studio(_job(2))
    _panel(view, studio_job)
    view._visual_editors[1].setPlainText("Hard cut to black.")  # noqa: SLF001

    def improve(job, visuals):  # type: ignore[no-untyped-def]
        raise RuntimeError("Improving the scene visuals failed: Provider unavailable.")

    view._content_intelligence_pipeline.improve_scene_visuals = improve  # type: ignore[method-assign]

    view._handle_improve_visuals()  # noqa: SLF001
    _panel(view, studio_job)

    assert any("Could not improve the scene visuals" in e for e in errors)
    assert view._visual_editors[1].toPlainText() == "Hard cut to black."  # noqa: SLF001


def test_undo_with_nothing_to_undo_does_nothing(qapp) -> None:  # type: ignore[no-untyped-def]
    view, studio_job, _errors = _studio(_job(2))

    view._handle_undo_improvements()  # noqa: SLF001

    assert view._visual_before_improve == {}  # noqa: SLF001


def test_the_result_message_is_repeated_next_to_the_buttons(qapp) -> None:  # type: ignore[no-untyped-def]
    """Live, 2026-10-14: the operator clicked the button twice and saw nothing, because the result
    appeared only at the top of the tab, far above the buttons below the boxes."""

    view, studio_job, _errors = _studio(_job(2))
    _panel(view, studio_job)
    view._visual_editors[1].setPlainText(
        "A jar rolls across the floor."
    )  # noqa: SLF001

    view._handle_improve_visuals()  # noqa: SLF001
    texts = _texts(_panel(view, studio_job))

    shown = [t for t in texts if "Checked 1 visual(s): no problems found" in t]
    assert len(shown) == 2
