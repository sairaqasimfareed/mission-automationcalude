"""The style line (2026-10-24): one line, entered once in Settings, added as the first words of
every compiled prompt. Radium came out photorealistic because the only "drawn" wording was the end
of the colour sentence while every other word (85mm, window light, New Jersey 1927) was photographic.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json  # noqa: E402
from collections.abc import Iterator  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton  # noqa: E402

from src.desktop.views.settings_view import SettingsView  # noqa: E402
from src.models.project_look import ProjectLook  # noqa: E402
from src.services.cinematic_prompt_compilation_service import (  # noqa: E402
    CinematicPromptCompilationService,
)
from src.services.style_line_store import (  # noqa: E402
    MAX_STYLE_LINE_CHARACTERS,
    StyleLineStore,
    clean_style_line,
    current_style_line,
    set_style_line_source,
    with_style_line,
)
from tests.test_cinematic_prompt_compilation_service import (  # noqa: E402
    _bible,
    _scene,
    _shot_plan,
)
from tests.test_settings_view import _configuration  # noqa: E402
from tests.test_settings_view import qapp as qapp  # noqa: E402,F401,PLC0414

_LINE = "Hand-drawn 2D animation, heavy black ink outlines, flat cel colour, never photorealistic"


@pytest.fixture(autouse=True)
def _no_leftover_source() -> Iterator[None]:
    yield
    set_style_line_source(lambda: "")


# ------------------------------------------------------------------ the store


def test_the_line_is_saved_and_read_back(tmp_path: Path) -> None:
    store = StyleLineStore(path=tmp_path / "style_line.json")

    assert store.load() == ""
    assert store.save(f"  {_LINE}\n") == _LINE
    assert StyleLineStore(path=tmp_path / "style_line.json").load() == _LINE


def test_an_empty_line_removes_the_style_line(tmp_path: Path) -> None:
    store = StyleLineStore(path=tmp_path / "style_line.json")
    store.save(_LINE)

    assert store.save("   ") == ""
    assert store.load() == ""


def test_a_missing_or_corrupt_or_odd_file_gives_no_line_and_no_error(
    tmp_path: Path,
) -> None:
    path = tmp_path / "style_line.json"

    for content in ("{not json", "[]", json.dumps({"style_line": 5}), "{}"):
        path.write_text(content, encoding="utf-8")

        assert StyleLineStore(path=path).load() == ""


def test_a_very_long_line_is_cut_at_a_word() -> None:
    long = "word " * 200
    cleaned = clean_style_line(long)

    assert len(cleaned) <= MAX_STYLE_LINE_CHARACTERS
    assert cleaned.endswith("word")


# ----------------------------------------------------- put in front of the look


def test_the_line_goes_in_front_of_the_look_and_never_twice() -> None:
    set_style_line_source(lambda: _LINE)

    assert with_style_line("Visual style - colour palette: slate.") == (
        f"{_LINE}. Visual style - colour palette: slate."
    )
    already = f"Visual style - colour palette: {_LINE}; camera: static."
    assert with_style_line(already) == already
    assert with_style_line("") == f"{_LINE}."


def test_with_no_source_or_a_failing_one_nothing_is_added() -> None:
    assert with_style_line("look") == "look"

    def boom() -> str:
        raise OSError("disk")

    set_style_line_source(boom)

    assert current_style_line() == "" and with_style_line("look") == "look"


# ------------------------------------------------------- through the compiler


def _prompt_text(project_look: ProjectLook | None) -> str:
    package = CinematicPromptCompilationService().compile(
        scenes=[_scene(1)],
        shot_plan=_shot_plan(),
        visual_continuity_bible=_bible(),
        production_semantic_brief=None,
        script_lock_hash="hash123",
        project_look=project_look,
    )
    prompt = package.prompt_for_scene(1)
    assert prompt is not None

    return prompt.prompt_text


def test_every_compiled_prompt_starts_with_the_style_line() -> None:
    set_style_line_source(lambda: _LINE)

    for look in (None, ProjectLook(color_palette="slate and ink")):
        assert _prompt_text(look).startswith(_LINE)


def test_without_a_style_line_the_prompt_is_as_before() -> None:
    assert not _prompt_text(ProjectLook(color_palette="slate")).startswith("Hand-drawn")


# ------------------------------------------------------------- the Settings box


def test_the_settings_box_shows_the_saved_line_and_saves_a_new_one(
    qapp: QApplication,  # noqa: F811
    tmp_path: Path,
) -> None:
    store = StyleLineStore(path=tmp_path / "style_line.json")
    store.save("Old line")
    view = SettingsView(
        get_configuration=_configuration,
        get_style_line=store.load,
        save_style_line=store.save,
    )
    edit = next(e for e in view.findChildren(QLineEdit))

    assert edit.text() == "Old line"

    edit.setText(f"  {_LINE}  ")
    next(
        b for b in view.findChildren(QPushButton) if b.text() == "Save style line"
    ).click()

    assert store.load() == _LINE and edit.text() == _LINE


def test_settings_without_the_style_line_hooks_has_no_such_box(
    qapp: QApplication,  # noqa: F811
) -> None:
    view = SettingsView(get_configuration=_configuration)

    assert not [
        b for b in view.findChildren(QPushButton) if b.text() == "Save style line"
    ]
