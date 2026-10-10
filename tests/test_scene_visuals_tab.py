"""
The "Scene visuals" tab, next to "Scene planning" in Content Studio (2026-10-10). The operator pastes a
table of narration and on-screen description (matched to the scenes by narration text), previews the
match, assigns what could not be found, and applies - or types a visual under any scene. The visuals live
on the job (`VideoJob.scene_visual_plan`); the paste box, the preview and the half-typed boxes are screen
state only. A bad paste is reported inline, never in a dialog.
"""

from __future__ import annotations

from PySide6.QtWidgets import QPushButton, QTextEdit, QVBoxLayout, QWidget

from src.desktop.views.content_studio_view import _CI_STAGES
from src.models.scene_visual import SceneVisual, SceneVisualPlan, narration_key
from src.models.shot_planning import CinematicShotPlan
from tests.test_scene_detail import _job
from tests.test_suggestions import (
    _studio,
    _texts,
)
from tests.test_suggestions import (
    qapp as qapp,  # noqa: PLC0414 - fixture
)

_TABLE = (
    "#\tNarration\tOn screen\n"
    "1\tNarration 1.\tA pale figure in a doorway\n"
    "2\tNarration 2.\tThe lamp gutters\n"
)


# A rendered panel's widgets are deleted with the QWidget holding them, and the view keeps references
# to some of them (the boxes, the dropdowns): hold on to every holder for the whole test run.
_ALIVE: list[QWidget] = []


def _panel(view, job) -> QWidget:  # type: ignore[no-untyped-def]
    holder = QWidget()
    _ALIVE.append(holder)
    layout = QVBoxLayout(holder)
    view._render_scene_visuals_panel(layout, job)  # noqa: SLF001

    return holder


def _studio_with_scenes(count: int = 3):  # type: ignore[no-untyped-def]
    view, studio_job, errors = _studio(_job(count))

    return view, studio_job, errors


# -------------------------------------------------------------------------- placement


def test_the_tab_sits_right_after_scene_planning() -> None:
    keys = [key for key, _label in _CI_STAGES]

    assert keys.index("scene_visuals") == keys.index("scene_planning") + 1
    assert dict(_CI_STAGES)["scene_visuals"] == "Scene visuals"


def test_the_stage_panel_has_no_run_or_review_row(qapp) -> None:  # type: ignore[no-untyped-def]
    view, studio_job, _errors = _studio_with_scenes()
    holder = QWidget()
    layout = QVBoxLayout(holder)

    view._build_ci_stage_panel(
        layout, studio_job, "scene_visuals", "Scene visuals"
    )  # noqa: SLF001
    texts = _texts(holder)

    assert "Match to scenes" in texts
    assert not any(t.startswith("Run ") for t in texts)
    assert "Review" not in texts


def test_running_every_listed_stage_in_order_never_fails_on_the_panel_only_tab(qapp) -> None:  # type: ignore[no-untyped-def]
    """A test and a user can both reach the generic runner for any listed stage; the visuals tab
    has nothing to run, so it must do nothing instead of failing."""

    view, studio_job, errors = _studio_with_scenes()

    view._handle_run_ci_stage("scene_visuals")  # noqa: SLF001

    assert errors == []
    assert studio_job.scene_visual_plan is None


def test_without_scenes_the_tab_says_what_is_missing(qapp) -> None:  # type: ignore[no-untyped-def]
    view, studio_job, _errors = _studio_with_scenes()
    studio_job.scenes = []

    texts = _texts(_panel(view, studio_job))

    assert "Requires scene planning first." in texts
    assert "Match to scenes" not in texts


# --------------------------------------------------------------------------- the boxes


def test_every_scene_gets_an_empty_visual_box(qapp) -> None:  # type: ignore[no-untyped-def]
    view, studio_job, _errors = _studio_with_scenes(3)

    holder = _panel(view, studio_job)
    texts = _texts(holder)

    assert sorted(view._visual_editors) == [1, 2, 3]  # noqa: SLF001
    assert all(
        e.toPlainText() == "" for e in view._visual_editors.values()
    )  # noqa: SLF001
    assert "0 of 3 scene(s) have a visual" in texts
    assert "Save visuals" in texts and "Remove all visuals" in texts
    assert (
        len(holder.findChildren(QTextEdit)) == 1 + 3
    )  # the paste box and one per scene


def test_a_typed_visual_is_saved_with_its_narration_and_marked_hand_edited(qapp) -> None:  # type: ignore[no-untyped-def]
    view, studio_job, errors = _studio_with_scenes(3)
    _panel(view, studio_job)
    view._visual_editors[2].setPlainText("  A hand   at the window  ")  # noqa: SLF001

    view._handle_save_visuals(False)  # noqa: SLF001

    plan = studio_job.scene_visual_plan
    assert plan is not None and len(plan.visuals) == 1
    entry = plan.visuals[0]
    assert (entry.scene_number, entry.text, entry.hand_edited) == (
        2,
        "A hand at the window",
        True,
    )
    assert entry.narration_key == narration_key("Narration 2.")
    assert studio_job.current_scene_visuals == {2: "A hand at the window"}
    assert errors == []


def test_saving_without_a_change_keeps_the_same_plan_and_revision(qapp) -> None:  # type: ignore[no-untyped-def]
    view, studio_job, _errors = _studio_with_scenes(2)
    studio_job.scene_visual_plan = SceneVisualPlan(
        visuals=[
            SceneVisual(
                scene_number=1,
                text="A figure",
                narration_key=narration_key("Narration 1."),
            )
        ]
    )
    before = studio_job.scene_visual_plan
    _panel(view, studio_job)
    view._handle_save_visuals(False)  # noqa: SLF001

    assert studio_job.scene_visual_plan is before


def test_emptying_every_box_removes_the_plan(qapp) -> None:  # type: ignore[no-untyped-def]
    view, studio_job, _errors = _studio_with_scenes(2)
    studio_job.scene_visual_plan = SceneVisualPlan(
        visuals=[
            SceneVisual(
                scene_number=1,
                text="A figure",
                narration_key=narration_key("Narration 1."),
            )
        ]
    )
    _panel(view, studio_job)
    view._visual_editors[1].setPlainText("")  # noqa: SLF001

    view._handle_save_visuals(False)  # noqa: SLF001

    assert studio_job.scene_visual_plan is None


def test_remove_all_clears_the_plan(qapp) -> None:  # type: ignore[no-untyped-def]
    view, studio_job, _errors = _studio_with_scenes(2)
    studio_job.scene_visual_plan = SceneVisualPlan(
        visuals=[
            SceneVisual(
                scene_number=1,
                text="A figure",
                narration_key=narration_key("Narration 1."),
            )
        ]
    )

    view._handle_clear_visuals()  # noqa: SLF001

    assert studio_job.scene_visual_plan is None


def test_text_typed_into_a_box_survives_a_redraw(qapp) -> None:  # type: ignore[no-untyped-def]
    view, studio_job, _errors = _studio_with_scenes(2)
    _panel(view, studio_job)
    view._visual_editors[1].setPlainText("Half typed")  # noqa: SLF001

    _panel(view, studio_job)  # the screen is rebuilt, e.g. after an assignment

    assert view._visual_editors[1].toPlainText() == "Half typed"  # noqa: SLF001


# ------------------------------------------------------------------------ paste + match


def test_the_paste_box_takes_plain_text_only(qapp) -> None:  # type: ignore[no-untyped-def]
    """Live, 2026-10-10: a table copied from a page pasted as a rendered rich-text table whose
    cells read back as separate lines, with nothing between the columns, and the match failed.
    """

    from PySide6.QtCore import QMimeData

    view, studio_job, _errors = _studio_with_scenes(2)
    _panel(view, studio_job)
    editor = view._visual_paste_editor  # noqa: SLF001

    assert editor is not None and editor.acceptRichText() is False

    mime = QMimeData()
    mime.setHtml(
        "<table><tr><td>1</td><td>Narration 1.</td><td>A figure</td></tr></table>"
    )
    mime.setText("1\tNarration 1.\tA figure")
    editor.insertFromMimeData(mime)

    assert editor.toPlainText() == "1\tNarration 1.\tA figure"


def test_matching_fills_every_matched_scene_box_and_saves_nothing_yet(qapp) -> None:  # type: ignore[no-untyped-def]
    view, studio_job, _errors = _studio_with_scenes(3)
    view._visual_paste_text = _TABLE  # noqa: SLF001

    view._handle_match_visuals()  # noqa: SLF001
    texts = _texts(_panel(view, studio_job))

    editors = view._visual_editors  # noqa: SLF001
    assert editors[1].toPlainText() == "A pale figure in a doorway."
    assert editors[2].toPlainText() == "The lamp gutters."
    assert editors[3].toPlainText() == ""  # the table did not reach scene 3
    assert any(
        "2 of 2 row(s) placed" in t and "1 scene(s) without a visual" in t
        for t in texts
    )
    assert any("not saved yet" in t for t in texts)
    assert "Save visuals" in texts
    assert studio_job.scene_visual_plan is None


def test_saving_after_a_match_stores_the_visuals_without_calling_them_hand_edited(qapp) -> None:  # type: ignore[no-untyped-def]
    view, studio_job, errors = _studio_with_scenes(3)
    view._visual_paste_text = _TABLE  # noqa: SLF001
    view._handle_match_visuals()  # noqa: SLF001
    _panel(view, studio_job)

    view._handle_save_visuals(False)  # noqa: SLF001

    assert studio_job.current_scene_visuals == {
        1: "A pale figure in a doorway.",
        2: "The lamp gutters.",
    }
    assert studio_job.scene_visual_plan is not None
    assert [v.hand_edited for v in studio_job.scene_visual_plan.visuals] == [
        False,
        False,
    ]
    assert view._visual_match is None  # noqa: SLF001
    assert errors == []


def test_text_edited_after_a_match_is_saved_as_hand_edited(qapp) -> None:  # type: ignore[no-untyped-def]
    view, studio_job, _errors = _studio_with_scenes(3)
    view._visual_paste_text = _TABLE  # noqa: SLF001
    view._handle_match_visuals()  # noqa: SLF001
    _panel(view, studio_job)
    view._visual_editors[2].setPlainText("The lamp goes out")  # noqa: SLF001

    view._handle_save_visuals(False)  # noqa: SLF001

    plan = studio_job.scene_visual_plan
    assert plan is not None
    assert {v.scene_number: v.hand_edited for v in plan.visuals} == {1: False, 2: True}
    assert studio_job.current_scene_visuals[2] == "The lamp goes out"


def test_a_match_replaces_the_box_of_a_scene_it_reaches_and_keeps_the_others(qapp) -> None:  # type: ignore[no-untyped-def]
    view, studio_job, _errors = _studio_with_scenes(3)
    studio_job.scene_visual_plan = SceneVisualPlan(
        visuals=[
            SceneVisual(
                scene_number=3, text="Kept", narration_key=narration_key("Narration 3.")
            ),
            SceneVisual(
                scene_number=1, text="Old", narration_key=narration_key("Narration 1.")
            ),
        ]
    )
    view._visual_paste_text = "1\tNarration 1.\tNew one\n"  # noqa: SLF001

    view._handle_match_visuals()  # noqa: SLF001
    _panel(view, studio_job)
    view._handle_save_visuals(False)  # noqa: SLF001

    assert studio_job.current_scene_visuals == {1: "New one.", 3: "Kept"}


def test_a_paste_that_is_not_a_table_is_reported_inline_not_in_a_dialog(qapp) -> None:  # type: ignore[no-untyped-def]
    view, studio_job, errors = _studio_with_scenes(2)
    view._visual_paste_text = "just some words"  # noqa: SLF001

    view._handle_match_visuals()  # noqa: SLF001
    texts = _texts(_panel(view, studio_job))

    assert any("with its columns" in t for t in texts)
    assert view._visual_match is None  # noqa: SLF001
    assert errors == []


def test_a_table_with_every_cell_on_its_own_line_fills_the_boxes_too(qapp) -> None:  # type: ignore[no-untyped-def]
    """The exact shape of the live failure: a header of three lines, then number, narration and
    on-screen text each on a line of their own."""

    view, studio_job, _errors = _studio_with_scenes(3)
    view._visual_paste_text = (  # noqa: SLF001
        "\n#\nNarration\nOn screen\n"
        "1\nNarration 1.\nA pale figure in a doorway\n"
        "2\nNarration 2.\nThe lamp gutters\n"
    )

    view._handle_match_visuals()  # noqa: SLF001
    _panel(view, studio_job)

    assert view._visual_message == ""  # noqa: SLF001
    assert (
        view._visual_editors[1].toPlainText() == "A pale figure in a doorway."
    )  # noqa: SLF001
    assert view._visual_editors[2].toPlainText() == "The lamp gutters."  # noqa: SLF001


def test_a_row_that_is_not_in_the_script_can_be_given_a_scene(qapp) -> None:  # type: ignore[no-untyped-def]
    view, studio_job, _errors = _studio_with_scenes(3)
    view._visual_paste_text = (
        _TABLE + "3\tA line the script never says\tA scream\n"
    )  # noqa: SLF001
    view._handle_match_visuals()  # noqa: SLF001
    texts = _texts(_panel(view, studio_job))

    assert any(t.startswith("Row 3 not found in the script") for t in texts)
    assert "Use this scene" in texts
    assert view._visual_editors[3].toPlainText() == ""  # noqa: SLF001

    view._visual_assign_selects[3].setCurrentIndex(2)  # noqa: SLF001 - Scene 3
    view._handle_assign_visual_row(3)  # noqa: SLF001
    texts = _texts(_panel(view, studio_job))

    assert not any(t.startswith("Row 3 not found") for t in texts)
    assert view._visual_editors[3].toPlainText() == "A scream."  # noqa: SLF001
    # the boxes the match had already filled are still filled
    assert (
        view._visual_editors[1].toPlainText() == "A pale figure in a doorway."
    )  # noqa: SLF001


def test_clearing_the_matches_empties_the_filled_boxes_and_saves_nothing(qapp) -> None:  # type: ignore[no-untyped-def]
    view, studio_job, _errors = _studio_with_scenes(2)
    view._visual_paste_text = _TABLE  # noqa: SLF001
    view._handle_match_visuals()  # noqa: SLF001

    view._handle_discard_visual_match()  # noqa: SLF001
    _panel(view, studio_job)

    assert view._visual_match is None  # noqa: SLF001
    assert view._visual_editors[1].toPlainText() == ""  # noqa: SLF001
    assert studio_job.scene_visual_plan is None


# ------------------------------------------------------------------------------ apply


def test_save_and_rebuild_also_runs_the_rebuild(qapp) -> None:  # type: ignore[no-untyped-def]
    view, studio_job, _errors = _studio_with_scenes(3)
    rebuilt: list[bool] = []
    view._content_intelligence_pipeline.rebuild_for_scene_visuals = (  # type: ignore[method-assign]
        lambda job: rebuilt.append(True) or job
    )
    view._visual_paste_text = _TABLE  # noqa: SLF001
    view._handle_match_visuals()  # noqa: SLF001
    _panel(view, studio_job)

    view._handle_save_visuals(True)  # noqa: SLF001

    assert rebuilt == [True]
    assert studio_job.scene_visual_plan is not None


def test_a_plain_save_does_not_rebuild(qapp) -> None:  # type: ignore[no-untyped-def]
    view, studio_job, _errors = _studio_with_scenes(3)
    rebuilt: list[bool] = []
    view._content_intelligence_pipeline.rebuild_for_scene_visuals = (  # type: ignore[method-assign]
        lambda job: rebuilt.append(True) or job
    )
    view._visual_paste_text = _TABLE  # noqa: SLF001
    view._handle_match_visuals()  # noqa: SLF001
    _panel(view, studio_job)

    view._handle_save_visuals(False)  # noqa: SLF001

    assert rebuilt == []


def test_the_handlers_do_not_crash_with_nothing_to_act_on(qapp) -> None:  # type: ignore[no-untyped-def]
    view, studio_job, _errors = _studio_with_scenes(2)

    view._handle_assign_visual_row(1)  # noqa: SLF001 - no match
    view._handle_discard_visual_match()  # noqa: SLF001
    view._handle_save_visuals(False)  # noqa: SLF001 - no boxes drawn yet

    assert studio_job.scene_visual_plan is None


# --------------------------------------------------------------------------- warnings


def test_visuals_for_changed_narration_are_flagged_and_not_used(qapp) -> None:  # type: ignore[no-untyped-def]
    view, studio_job, _errors = _studio_with_scenes(2)
    studio_job.scene_visual_plan = SceneVisualPlan(
        visuals=[
            SceneVisual(
                scene_number=1,
                text="Old visual",
                narration_key=narration_key("Other text."),
            )
        ]
    )

    texts = _texts(_panel(view, studio_job))

    assert any("narration of scene(s) 1 changed" in t for t in texts)
    assert any("Earlier visual (narration has changed): Old visual" in t for t in texts)
    assert "0 of 2 scene(s) have a visual" in texts


def test_a_shot_plan_made_before_the_visuals_is_flagged(qapp) -> None:  # type: ignore[no-untyped-def]
    view, studio_job, _errors = _studio_with_scenes(2)
    studio_job.cinematic_shot_plan = CinematicShotPlan(script_lock_hash="hash123")
    studio_job.scene_visual_plan = SceneVisualPlan(
        visuals=[
            SceneVisual(
                scene_number=1,
                text="A figure",
                narration_key=narration_key("Narration 1."),
            )
        ]
    )

    texts = _texts(_panel(view, studio_job))

    assert any("made before these visuals" in t for t in texts)

    studio_job.cinematic_shot_plan.visual_revision = (
        studio_job.scene_visual_plan.revision
    )
    texts = _texts(_panel(view, studio_job))

    assert not any("made before these visuals" in t for t in texts)


def test_the_buttons_exist_and_are_real_buttons(qapp) -> None:  # type: ignore[no-untyped-def]
    view, studio_job, _errors = _studio_with_scenes(2)

    holder = _panel(view, studio_job)
    buttons = {b.text(): b for b in holder.findChildren(QPushButton)}

    assert buttons["Remove all visuals"].isEnabled() is False  # nothing to remove yet
    assert "Save and rebuild shots, scene text and prompts" in buttons
