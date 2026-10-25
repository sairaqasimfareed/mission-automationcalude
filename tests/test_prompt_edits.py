"""Editable prompts (2026-10-24): the Prompts tab boxes can be edited by hand and are saved when the
operator clicks away; "Reset to automatic" puts the generated text back. The automatic prompt is
never overwritten - the edit is kept beside it on the project and sent instead of it."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

from src.desktop.views.compiled_prompt_view import _PromptTextEdit  # noqa: E402
from src.models.cinematic_prompt import (  # noqa: E402
    CinematicPromptPackage,
    ResolvedCinematicPrompt,
)
from src.models.prompt_edit import PromptEdit  # noqa: E402
from src.models.video_job import VideoJob  # noqa: E402
from src.services.prompt_edit_service import (  # noqa: E402
    edit_for,
    edited_text_for,
    is_stale,
    keep_edit_against_current_prompt,
    reset_edit,
    save_edit,
)
from tests.test_compiled_prompt_view import (  # noqa: E402
    _SCRIPT_LOCK_HASH,
    _job,
    _scene,
    _view,
)
from tests.test_compiled_prompt_view import (  # noqa: E402
    qapp as qapp,  # noqa: PLC0414
)

_AUTOMATIC = "The automatic prompt for scene one."


def _plain_job() -> VideoJob:
    return VideoJob(project_name="P", channel_name="C", niche="n", topic="T")


# ------------------------------------------------------------------ the service


def test_an_edit_is_stored_found_and_replaced_not_duplicated() -> None:
    job = _plain_job()

    assert save_edit(job, 1, 0, "  My wording  ", automatic_text=_AUTOMATIC) is True
    assert edited_text_for(job, 1) == "My wording"
    assert edited_text_for(job, 2) is None
    assert edited_text_for(job, 1, 1) is None

    save_edit(job, 1, 0, "Changed again", automatic_text=_AUTOMATIC)

    assert [e.text for e in job.prompt_edits] == ["Changed again"]


def test_text_equal_to_the_automatic_prompt_or_empty_is_not_kept_as_an_edit() -> None:
    job = _plain_job()
    save_edit(job, 1, 0, "My wording", automatic_text=_AUTOMATIC)

    # opening the box and clicking away with the automatic text puts things back
    assert save_edit(job, 1, 0, f"  {_AUTOMATIC}\n", automatic_text=_AUTOMATIC) is False
    assert job.prompt_edits == []

    save_edit(job, 1, 0, "My wording", automatic_text=_AUTOMATIC)
    assert save_edit(job, 1, 0, "   ", automatic_text=_AUTOMATIC) is False
    assert job.prompt_edits == []


def test_each_part_of_a_split_scene_has_its_own_edit_and_reset_removes_only_one() -> (
    None
):
    job = _plain_job()
    save_edit(job, 3, 0, "part one mine", automatic_text="a")
    save_edit(job, 3, 1, "part two mine", automatic_text="b")

    assert reset_edit(job, 3, 1) is True
    assert reset_edit(job, 3, 1) is False
    assert edited_text_for(job, 3, 0) == "part one mine"
    assert edited_text_for(job, 3, 1) is None


def test_an_edit_is_stale_when_the_automatic_prompt_has_moved_on() -> None:
    job = _plain_job()
    save_edit(job, 1, 0, "Mine", automatic_text="old automatic text")
    edit = edit_for(job, 1)
    assert edit is not None

    assert not is_stale(edit, "old   automatic text")  # spacing does not count
    assert is_stale(edit, "a new automatic text")

    keep_edit_against_current_prompt(job, 1, 0, "a new automatic text")

    assert not is_stale(edit, "a new automatic text")


def test_an_empty_prompt_edit_is_refused_by_the_model() -> None:
    with pytest.raises(ValueError):
        PromptEdit(scene_number=1, text="   ")


def test_edits_survive_saving_and_loading_the_project() -> None:
    job = _plain_job()
    save_edit(job, 2, 1, "Mine", automatic_text="auto")

    again = VideoJob.model_validate_json(job.model_dump_json())

    assert edited_text_for(again, 2, 1) == "Mine"


def test_a_project_saved_before_edits_existed_loads_without_any() -> None:
    data = _plain_job().model_dump()
    data.pop("prompt_edits")

    assert VideoJob.model_validate(data).prompt_edits == []


# ---------------------------------------------------------------- the Prompts tab


def _tab_job() -> VideoJob:
    package = CinematicPromptPackage(
        script_lock_hash=_SCRIPT_LOCK_HASH,
        prompts=[
            ResolvedCinematicPrompt(
                scene_number=1,
                script_lock_hash=_SCRIPT_LOCK_HASH,
                prompt_text=_AUTOMATIC,
            )
        ],
    )

    return _job(scenes=[_scene(scene_number=1)], cinematic_prompt_package=package)


def _open(job: VideoJob):  # type: ignore[no-untyped-def]
    view = _view()
    view._job_store.add(job)  # noqa: SLF001
    view.set_job(job.id)
    view.refresh(job)

    return view


def _box(view) -> _PromptTextEdit:  # type: ignore[no-untyped-def]
    return view.findChildren(_PromptTextEdit)[0]


def _buttons(view) -> dict[str, QPushButton]:  # type: ignore[no-untyped-def]
    return {b.text(): b for b in view.findChildren(QPushButton)}


def test_the_prompt_box_is_editable_and_saves_when_the_operator_clicks_away(
    qapp: QApplication,  # noqa: F811
) -> None:
    job = _tab_job()
    view = _open(job)
    box = _box(view)

    assert not box.isReadOnly()
    assert not _buttons(view)["Reset to automatic"].isEnabled()

    box.setPlainText("My own prompt for scene one.")
    box.focus_lost.emit()

    assert edited_text_for(job, 1) == "My own prompt for scene one."
    assert _buttons(view)["Reset to automatic"].isEnabled()
    # the automatic prompt itself is untouched
    assert job.cinematic_prompt_package is not None
    automatic = job.cinematic_prompt_package.prompt_for_scene(1)
    assert automatic is not None and automatic.prompt_text == _AUTOMATIC


def test_reset_to_automatic_removes_the_edit_and_shows_the_generated_text_again(
    qapp: QApplication,  # noqa: F811
) -> None:
    job = _tab_job()
    save_edit(job, 1, 0, "Edited earlier", automatic_text=_AUTOMATIC)
    view = _open(job)

    assert _box(view).toPlainText() == "Edited earlier"
    assert _buttons(view)["Reset to automatic"].isEnabled()

    _buttons(view)["Reset to automatic"].click()
    # the rebuilt tab replaces the old boxes; Qt deletes the old ones on the next event pass
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    assert edited_text_for(job, 1) is None
    assert _box(view).toPlainText() == _AUTOMATIC


def test_an_edit_whose_automatic_prompt_changed_says_so_and_keep_mine_clears_it(
    qapp: QApplication,  # noqa: F811
) -> None:
    job = _tab_job()
    save_edit(
        job, 1, 0, "Edited earlier", automatic_text="the automatic text of last week"
    )
    view = _open(job)

    texts = [label.text() for label in view.findChildren(QLabel)]
    assert any("automatic prompt has changed" in t for t in texts)
    assert not _buttons(view)["Keep mine"].isHidden()

    _buttons(view)["Keep mine"].click()

    assert _buttons(view)["Keep mine"].isHidden()
    assert edited_text_for(job, 1) == "Edited earlier"


def test_clicking_away_with_the_automatic_text_does_not_make_an_edit(
    qapp: QApplication,  # noqa: F811
) -> None:
    job = _tab_job()
    view = _open(job)
    box = _box(view)

    box.setPlainText(f"{_AUTOMATIC}  ")
    box.focus_lost.emit()

    assert job.prompt_edits == []


def test_copy_puts_the_edited_prompt_on_the_clipboard(
    qapp: QApplication,  # noqa: F811
) -> None:
    job = _tab_job()
    view = _open(job)
    box = _box(view)
    box.setPlainText("Copy this edited prompt.")

    _buttons(view)["Copy prompt"].click()

    clipboard = QApplication.clipboard()
    assert clipboard is not None
    assert "Copy this edited prompt." in clipboard.text()
    assert _AUTOMATIC not in clipboard.text()


def test_the_exported_prompt_file_carries_the_operators_edit() -> None:
    from src.services.scene_prompt_export_service import ScenePromptExportService

    job = _tab_job()
    text = ScenePromptExportService().to_text(
        job.scenes,
        cinematic_prompt_package=job.cinematic_prompt_package,
        edited_prompts={1: "Exported edited prompt."},
    )

    assert "Prompt: Exported edited prompt." in text
    assert _AUTOMATIC not in text

    untouched = ScenePromptExportService().to_text(
        job.scenes, cinematic_prompt_package=job.cinematic_prompt_package
    )

    assert f"Prompt: {_AUTOMATIC}" in untouched
