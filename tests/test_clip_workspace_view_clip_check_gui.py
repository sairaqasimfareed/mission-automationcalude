"""
Clip check card (2026-10-03): after "Generate all scenes" - possibly left
unattended - the Clip Workspace must say whether every scene got the right clip.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path  # noqa: E402
from unittest.mock import patch  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

from src.desktop.views.clip_workspace_view import ClipWorkspaceView  # noqa: E402
from src.models.clip_attachment_verification import (  # noqa: E402
    ClipAttachmentVerificationReport,
    ClipVerificationIssue,
    ClipVerificationIssueCode,
    ClipVerificationSeverity,
    SceneClipVerification,
)
from src.models.video_job import VideoJob  # noqa: E402
from src.services.clip_attachment_verification_service import (  # noqa: E402
    clip_signature,
)
from tests.test_clip_workspace_view_scene_generation import (  # noqa: E402
    _build_view,
    _FakeJobStore,
    _FakeSceneVideoGenerationService,
    _find_buttons,
    _job,
    qapp,  # noqa: F401 - fixture
)


class _StubVerifier:
    """Stands in for ClipAttachmentVerificationService: no ffmpeg, a canned
    report, and a record of how often it was asked."""

    def __init__(self, *, raises: bool = False, report_factory=None) -> None:  # type: ignore[no-untyped-def]
        self.calls = 0
        self._raises = raises
        self._report_factory = report_factory

    def verify(self, job: VideoJob) -> ClipAttachmentVerificationReport:
        self.calls += 1

        if self._raises:
            raise RuntimeError("probe exploded")

        if self._report_factory is not None:
            return self._report_factory(job)

        return ClipAttachmentVerificationReport(
            clip_signature=clip_signature(job),
            scenes=[
                SceneClipVerification(
                    scene_number=scene.scene_number,
                    scene_title=scene.title,
                    narration=scene.narration,
                )
                for scene in job.scenes
            ],
        )


def _view_with(job: VideoJob, verifier: _StubVerifier, store: _FakeJobStore | None = None):  # type: ignore[no-untyped-def]
    service = _FakeSceneVideoGenerationService()
    view = _build_view(job, service=service, job_store=store)  # type: ignore[arg-type]
    view._clip_verification_service = verifier  # type: ignore[assignment]  # noqa: SLF001
    view.refresh(job)

    return view, service


def _texts(view: ClipWorkspaceView) -> list[str]:
    """Visible label text. The tests give the view a no-op on_change, so the
    refresh the real window triggers is done here, and deleteLater'd widgets
    from the previous build are flushed so they are not read as still there."""

    job = view._current_job()  # noqa: SLF001

    if job is not None:
        view.refresh(job)

    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    return [label.text() for label in view.findChildren(QLabel)]


def _flush_deleted_widgets() -> None:
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _wait_for(app: QApplication, threads) -> None:  # type: ignore[no-untyped-def]
    for thread, _worker in list(threads.values()):
        thread.wait(3000)

    for _ in range(30):
        app.processEvents()


def _click(view: ClipWorkspaceView, text: str) -> None:
    next(b for b in _find_buttons(view) if b.text() == text).click()


def test_a_project_never_checked_says_so_and_offers_the_check(
    qapp: QApplication,  # noqa: F811
) -> None:
    job = _job(1, 2)
    view, _ = _view_with(job, _StubVerifier())

    assert any("Not checked yet" in text for text in _texts(view))
    assert next(
        b for b in _find_buttons(view) if b.text() == "Check clips now"
    ).isEnabled()


def test_generate_all_checks_the_clips_by_itself_and_saves_the_verdict(
    qapp: QApplication,  # noqa: F811
) -> None:
    job = _job(1, 2)
    store = _FakeJobStore(job)
    verifier = _StubVerifier()
    view, service = _view_with(job, verifier, store)

    _click(view, "Generate all scenes")
    _wait_for(qapp, view._generation_threads)  # noqa: SLF001

    assert service.generate_all_calls == 1
    assert verifier.calls == 1
    assert job.clip_verification_report is not None
    assert len(job.clip_verification_report.scenes) == 2
    # The verdict reached the store, so it survives a restart.
    assert any(saved.clip_verification_report is not None for saved in store.added)
    assert any("All 2 scene(s)" in text for text in _texts(view))


def test_generating_one_scene_does_not_run_the_whole_project_check(
    qapp: QApplication,  # noqa: F811
) -> None:
    job = _job(1)
    verifier = _StubVerifier()
    view, _ = _view_with(job, verifier)

    _click(view, "Generate")
    _wait_for(qapp, view._generation_threads)  # noqa: SLF001

    assert verifier.calls == 0


def test_a_check_that_crashes_never_fails_the_generation(
    qapp: QApplication,  # noqa: F811
) -> None:
    job = _job(1, 2)
    verifier = _StubVerifier(raises=True)
    view, service = _view_with(job, verifier)

    _click(view, "Generate all scenes")
    _wait_for(qapp, view._generation_threads)  # noqa: SLF001

    assert verifier.calls == 1
    assert len(job.video_clips) == 2  # generation itself finished normally
    assert job.clip_verification_report is None
    assert not any("Simulated" in error for error in job.errors)


def test_a_run_that_fails_partway_still_gets_checked(
    qapp: QApplication,  # noqa: F811
) -> None:
    job = _job(1, 2, 3)
    store = _FakeJobStore(job)
    verifier = _StubVerifier()
    service = _FakeSceneVideoGenerationService(fail_on_scene=3)
    view = _build_view(job, service=service, job_store=store)  # type: ignore[arg-type]
    view._clip_verification_service = verifier  # type: ignore[assignment]  # noqa: SLF001

    with patch("src.desktop.views.clip_workspace_view.show_recoverable_error"):
        _click(view, "Generate all scenes")
        _wait_for(qapp, view._generation_threads)  # noqa: SLF001

    assert verifier.calls == 1
    assert job.clip_verification_report is not None


def test_check_clips_now_runs_off_the_gui_thread_and_shows_the_problems(
    qapp: QApplication,  # noqa: F811
    tmp_path: Path,
) -> None:
    job = _job(1, 2)
    job.clip_verification_report = None

    def factory(snapshot: VideoJob) -> ClipAttachmentVerificationReport:
        return ClipAttachmentVerificationReport(
            clip_signature=clip_signature(snapshot),
            scenes=[
                SceneClipVerification(scene_number=1, scene_title="Scene 1"),
                SceneClipVerification(
                    scene_number=2,
                    scene_title="Scene 2",
                    issues=[
                        ClipVerificationIssue(
                            code=ClipVerificationIssueCode.DUPLICATE_CONTENT,
                            severity=ClipVerificationSeverity.ERROR,
                            message="This is the same footage as scene 1 - "
                            "the wrong video may have been attached.",
                        )
                    ],
                ),
            ],
        )

    store = _FakeJobStore(job)
    view, _ = _view_with(job, _StubVerifier(report_factory=factory), store)

    _click(view, "Check clips now")

    assert next(
        b for b in _find_buttons(view) if "Checking" in b.text()
    ), "button shows progress while the check runs"

    _wait_for(qapp, view._verification_threads)  # noqa: SLF001

    assert job.clip_verification_report is not None
    texts = _texts(view)
    assert any("1 OK" in text and "1 with a problem" in text for text in texts)
    assert any("same footage as scene 1" in text for text in texts)
    assert any("#2 Scene 2 - Problem" in text for text in texts)
    assert any("#1 Scene 1 - OK" in text for text in texts)


def test_a_verdict_for_clips_that_have_since_changed_is_marked_out_of_date(
    qapp: QApplication,  # noqa: F811
) -> None:
    job = _job(1)
    job.clip_verification_report = ClipAttachmentVerificationReport(
        clip_signature="clips-as-they-were",
        scenes=[SceneClipVerification(scene_number=1, scene_title="Scene 1")],
    )
    view, _ = _view_with(job, _StubVerifier())

    assert any("Out of date" in text for text in _texts(view))
    assert not any("All 1 scene(s)" in text for text in _texts(view))


def test_a_real_thumbnail_is_shown_beside_the_scene(
    qapp: QApplication,  # noqa: F811
    tmp_path: Path,
) -> None:
    still = tmp_path / "still.png"
    image = QImage(320, 180, QImage.Format.Format_RGB32)
    image.fill(QColor("red"))
    assert image.save(str(still))

    job = _job(1)
    job.clip_verification_report = ClipAttachmentVerificationReport(
        clip_signature=clip_signature(job),
        scenes=[
            SceneClipVerification(
                scene_number=1, scene_title="Scene 1", thumbnail_file=str(still)
            )
        ],
    )
    view, _ = _view_with(job, _StubVerifier())
    _flush_deleted_widgets()

    pictures = [
        label
        for label in view.findChildren(QLabel)
        if label.pixmap() is not None
        and not label.pixmap().isNull()
        and label.pixmap().width() == 176
    ]

    assert len(pictures) == 1


def test_a_scene_without_a_thumbnail_says_no_preview(
    qapp: QApplication,  # noqa: F811
) -> None:
    job = _job(1)
    job.clip_verification_report = ClipAttachmentVerificationReport(
        clip_signature=clip_signature(job),
        scenes=[SceneClipVerification(scene_number=1, scene_title="Scene 1")],
    )
    view, _ = _view_with(job, _StubVerifier())

    assert "No preview" in _texts(view)


def test_the_check_button_is_disabled_while_generation_runs(
    qapp: QApplication,  # noqa: F811
) -> None:
    job = _job(1)
    view, _ = _view_with(job, _StubVerifier())
    view._generating_job_ids.add(job.id)  # noqa: SLF001
    view.refresh(job)
    _flush_deleted_widgets()

    button = next(
        b for b in view.findChildren(QPushButton) if "Check clips" in b.text()
    )

    assert not button.isEnabled()


@pytest.fixture(autouse=True)
def _isolate_default_thumbnail_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The views build a real default verifier that would write under
    data/clip_thumbnails relative to the working directory."""

    monkeypatch.chdir(tmp_path)
