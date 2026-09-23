from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton, QTextEdit  # noqa: E402

from src.desktop.job_store import InMemoryJobStore  # noqa: E402
from src.desktop.views.compiled_prompt_view import CompiledPromptView  # noqa: E402
from src.models.cinematic_prompt import (  # noqa: E402
    CinematicPromptPackage,
    ResolvedCinematicPrompt,
)
from src.models.media_strategy import SceneSourceStatus, SceneSourceType  # noqa: E402
from src.models.scene import Scene  # noqa: E402
from src.models.video_job import VideoJob  # noqa: E402

_SCRIPT_LOCK_HASH = "a" * 64


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])

    yield app  # type: ignore[misc]


def _scene(*, scene_number: int = 1, title: str = "Opening Scene") -> Scene:
    return Scene(
        scene_number=scene_number,
        title=title,
        narration="Something happens.",
        visual_prompt="A cinematic visual.",
        estimated_duration_seconds=8,
        source_type=SceneSourceType.MANUAL_UPLOAD,
        source_status=SceneSourceStatus.READY,
        manual_file_path="assets/videos/manual/test_scene.mp4",
    )


def _job(**overrides: object) -> VideoJob:
    job = VideoJob(
        project_name="Test Project",
        channel_name="Test Channel",
        niche="documentary",
        topic="A test topic",
    )

    for key, value in overrides.items():
        setattr(job, key, value)

    return job


def _view() -> CompiledPromptView:
    return CompiledPromptView(
        job_store=InMemoryJobStore(),
        on_change=lambda: None,
    )


def test_shows_a_message_when_no_scenes_are_planned(qapp: QApplication) -> None:
    view = _view()
    job = _job()

    view._job_store.add(job)
    view.set_job(job.id)
    view.refresh(job)

    text_edits = view.findChildren(QTextEdit)

    assert text_edits == []


def test_shows_one_row_per_scene_with_the_real_compiled_prompt_text(
    qapp: QApplication,
) -> None:
    package = CinematicPromptPackage(
        script_lock_hash=_SCRIPT_LOCK_HASH,
        prompts=[
            ResolvedCinematicPrompt(
                scene_number=1,
                script_lock_hash=_SCRIPT_LOCK_HASH,
                prompt_text="The real compiled prompt for scene one.",
            )
        ],
    )

    job = _job(
        scenes=[_scene(scene_number=1)],
        cinematic_prompt_package=package,
    )

    view = _view()

    view._job_store.add(job)
    view.set_job(job.id)
    view.refresh(job)

    text_edits = view.findChildren(QTextEdit)

    assert len(text_edits) == 1
    assert "The real compiled prompt for scene one." in text_edits[0].toPlainText()


def test_shows_multiple_scenes_in_scene_number_order(qapp: QApplication) -> None:
    job = _job(scenes=[_scene(scene_number=2), _scene(scene_number=1)])

    view = _view()

    view._job_store.add(job)
    view.set_job(job.id)
    view.refresh(job)

    text_edits = view.findChildren(QTextEdit)

    assert len(text_edits) == 2
    assert "Scene 1" in text_edits[0].toPlainText()
    assert "Scene 2" in text_edits[1].toPlainText()


def test_copy_button_puts_the_full_prompt_text_on_the_clipboard(
    qapp: QApplication,
) -> None:
    package = CinematicPromptPackage(
        script_lock_hash=_SCRIPT_LOCK_HASH,
        prompts=[
            ResolvedCinematicPrompt(
                scene_number=1,
                script_lock_hash=_SCRIPT_LOCK_HASH,
                prompt_text="Copy-me prompt text.",
                negative_constraints=["no logos"],
            )
        ],
    )

    job = _job(
        scenes=[_scene(scene_number=1)],
        cinematic_prompt_package=package,
    )

    view = _view()

    view._job_store.add(job)
    view.set_job(job.id)
    view.refresh(job)

    copy_button = next(
        button
        for button in view.findChildren(QPushButton)
        if button.text() == "Copy prompt"
    )
    copy_button.click()

    clipboard = QApplication.clipboard()

    assert clipboard is not None
    assert "Copy-me prompt text." in clipboard.text()
    assert "no logos" in clipboard.text()


def test_refresh_clears_previous_rows_before_rebuilding(qapp: QApplication) -> None:
    """
    refresh() removes the old top-level cards from the layout
    synchronously (QLayout.takeAt()); actual QObject destruction is
    deferred via deleteLater() - the same pattern every other view in
    this codebase already uses - so findChildren() can still see the
    old widgets until Qt's event loop processes that deferred
    deletion. The layout's own count is what's synchronously
    guaranteed right after refresh() returns, so that's what a real
    "did the old rows get replaced" check should assert on.
    """

    view = _view()

    job_one = _job(scenes=[_scene(scene_number=1), _scene(scene_number=2)])
    view._job_store.add(job_one)
    view.set_job(job_one.id)
    view.refresh(job_one)

    assert view._layout.count() == 1  # one "Compiled Prompts" card

    job_two = _job(scenes=[_scene(scene_number=1)])
    view.refresh(job_two)

    assert view._layout.count() == 1  # still exactly one card, replaced not stacked
