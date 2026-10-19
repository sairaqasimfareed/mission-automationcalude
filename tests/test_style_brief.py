"""
Style brief (2026-10-18): a series' visual style pasted once on the project - the look, locked sets, a recurring
persona, colour rules, how flashbacks differ. It is not part of the script and is never spoken; every step that
decides how the video looks is told it as binding, alongside the genre's own direction.
"""

from __future__ import annotations

from src.services.content_intelligence_pipeline import ContentIntelligencePipeline
from src.services.genre_visual_mood import genre_direction, visual_direction
from tests.test_content_intelligence_pipeline import _EchoStubLLMService, _job
from tests.test_genre_reaches_every_step import _LOOK_STEPS, _by_agent
from tests.test_suggestions import qapp as qapp  # noqa: PLC0414 - fixture

_BRIEF = (
    "VISUAL STYLE Anime courtroom, stark noir. The courtroom is the locked set: dark wood, a single high "
    "window. Colour coding: prosecution = crimson; defense = deep teal. Exhibit flashbacks render in warm sepia."
)


def test_without_a_brief_the_direction_is_exactly_the_genres() -> None:
    assert visual_direction("genre.horror") == genre_direction("genre.horror")
    assert visual_direction("genre.horror", "") == genre_direction("genre.horror")
    assert visual_direction("genre.horror", "   \n ") == genre_direction("genre.horror")
    assert visual_direction("genre.default", "") == ""


def test_a_brief_follows_the_genre_direction_and_is_marked_binding() -> None:
    text = visual_direction("genre.horror", _BRIEF)

    assert text.startswith(genre_direction("genre.horror"))
    assert "STYLE BRIEF FROM THE OPERATOR" in text
    assert "binding" in text
    assert "deep teal" in text and "warm sepia" in text


def test_a_genre_with_no_direction_still_carries_the_brief() -> None:
    text = visual_direction("genre.default", _BRIEF)

    assert text.startswith("STYLE BRIEF FROM THE OPERATOR")
    assert "locked set" in text


def test_a_very_long_brief_is_cut_to_the_supported_length() -> None:
    text = visual_direction("genre.default", "word " * 5000)

    assert len(text) < 6400


def test_saving_trims_and_caps_the_brief() -> None:
    job = _job()

    ContentIntelligencePipeline.set_style_brief(job, "   " + _BRIEF + "   ")
    assert job.style_brief == _BRIEF

    ContentIntelligencePipeline.set_style_brief(job, "x" * 9000)
    assert len(job.style_brief) == 6000

    ContentIntelligencePipeline.set_style_brief(job, "")
    assert job.style_brief == ""


def test_every_look_step_is_told_the_brief() -> None:
    stub = _EchoStubLLMService()
    pipeline = ContentIntelligencePipeline(llm_service=stub)  # type: ignore[arg-type]
    job = _job(genre_id="genre.horror")
    job.style_brief = _BRIEF

    pipeline.run_all(job)
    seen = _by_agent(stub)

    for agent in _LOOK_STEPS:
        assert agent in seen, agent
        assert all("deep teal" in prompt for prompt in seen[agent]), agent


def test_without_a_brief_no_look_step_mentions_one() -> None:
    stub = _EchoStubLLMService()
    pipeline = ContentIntelligencePipeline(llm_service=stub)  # type: ignore[arg-type]

    pipeline.run_all(_job(genre_id="genre.horror"))

    for agent in _LOOK_STEPS:
        assert all(
            "STYLE BRIEF FROM THE OPERATOR" not in prompt
            for prompt in _by_agent(stub)[agent]
        ), agent


def test_the_brief_box_shows_the_saved_text_and_saves_new_text(qapp) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QPushButton, QTextEdit, QVBoxLayout, QWidget

    from tests.test_scene_detail import _job as scene_job
    from tests.test_suggestions import _studio

    view, job, _errors = _studio(scene_job(2))
    job.style_brief = "Cold slate courtroom."
    holder = QWidget()
    view._render_style_brief_box(QVBoxLayout(holder), job)  # noqa: SLF001
    editors = holder.findChildren(QTextEdit)
    buttons = [b.text() for b in holder.findChildren(QPushButton)]

    assert [e.toPlainText() for e in editors] == ["Cold slate courtroom."]
    assert "Save style brief" in buttons

    editors[0].setPlainText(_BRIEF)
    view._handle_save_style_brief()  # noqa: SLF001
    saved = view._current_job()  # noqa: SLF001

    assert saved is not None and saved.style_brief == _BRIEF
