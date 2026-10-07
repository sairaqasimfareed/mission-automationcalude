from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading  # noqa: E402
import time  # noqa: E402
from collections.abc import Callable, Iterator  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest.mock import patch  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QLineEdit,
    QPushButton,
)  # noqa: E402

from src.desktop.job_store import InMemoryJobStore, JsonJobStore  # noqa: E402
from src.desktop.views.packaging_view import PackagingView  # noqa: E402
from src.models.audience_promise import AudiencePromise, PromiseStrength  # noqa: E402
from src.models.audio_timeline import AudioTimeline  # noqa: E402
from src.models.enums import JobStatus, WorkflowStage  # noqa: E402
from src.models.media_strategy import SceneSourceType  # noqa: E402
from src.models.render_orchestration_result import (  # noqa: E402
    RenderOrchestrationResult,
)
from src.models.render_result import RenderResult, RenderStatus  # noqa: E402
from src.models.research import ResearchResult, ResearchStatus  # noqa: E402
from src.models.scene import Scene  # noqa: E402
from src.models.script import Script, ScriptStatus  # noqa: E402
from src.models.thumbnail import ThumbnailTextPosition  # noqa: E402
from src.models.video_clip import VideoClip  # noqa: E402
from src.models.video_job import VideoJob  # noqa: E402
from src.models.video_timeline import VideoTimeline  # noqa: E402
from src.services.final_export.final_export_service import (  # noqa: E402
    FinalExportService,
)
from src.services.render_result_resolution_service import (  # noqa: E402
    replace_orchestration_render_result,
)


class _FakeOpeningTitleCardService:
    def __init__(self, *, result: RenderResult) -> None:
        self._result = result
        self.calls: list[dict[str, object]] = []

    def build(self, **kwargs: object) -> RenderResult:
        self.calls.append(kwargs)

        return self._result


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])

    yield app  # type: ignore[misc]


def _job(*, title_card_enabled: bool = True) -> VideoJob:
    job = VideoJob(
        project_name="Deep Sea Doc",
        channel_name="Ocean Channel",
        niche="documentary",
        topic="Giant squid",
        status=JobStatus.COMPLETED,
        current_stage=WorkflowStage.READY_FOR_UPLOAD,
    )
    job.title_card_enabled = title_card_enabled

    job.research = ResearchResult(
        topic="Giant squid",
        status=ResearchStatus.APPROVED,
        research_summary="Real research summary for the giant squid documentary.",
        prompt_version="test-1.0",
    )

    job.script = Script(
        title="Deep Sea Doc Script",
        content="Full narration text for the giant squid documentary.",
        prompt_version="test-1.0",
        word_count=8,
        estimated_duration_seconds=60,
        status=ScriptStatus.APPROVED,
    )

    job.audience_promise = AudiencePromise(
        topic=job.topic,
        target_audience="Marine biology enthusiasts.",
        platform="youtube",
        genre_id="genre.documentary",
        target_duration_seconds=60,
        intended_emotion="Awe.",
        central_curiosity="How giant squid survive in the deep ocean.",
        primary_question="What makes giant squid so elusive?",
        viewer_benefit="Understand a genuinely mysterious deep-sea creature.",
        expected_payoff="A clear picture of giant squid biology and behavior.",
        promise_strength=PromiseStrength.STRONG,
        prompt_version="test-1.0",
    )

    return job


def _successful_render_result(
    job: VideoJob, *, output_file: str = "outputs/main_render.mp4"
) -> RenderOrchestrationResult:
    return RenderOrchestrationResult(
        success=True,
        status=JobStatus.COMPLETED,
        current_stage=WorkflowStage.READY_FOR_UPLOAD,
        job=job,
        render_result=RenderResult(
            success=True,
            output_file=output_file,
            render_engine="ffmpeg",
            duration_seconds=60,
            status=RenderStatus.COMPLETED,
        ),
    )


def _view(
    *,
    on_change=lambda: None,
    tmp_path: Path,
    opening_title_card_service=None,
) -> PackagingView:
    return PackagingView(
        job_store=InMemoryJobStore(),
        seo_package_service=None,  # type: ignore[arg-type]
        thumbnail_package_service=None,  # type: ignore[arg-type]
        final_export_service=FinalExportService(export_root=tmp_path / "exports"),
        on_change=on_change,
        opening_title_card_service=opening_title_card_service,
    )


def _wait_for_generation(
    view: PackagingView, qapp: QApplication, *, timeout_seconds: float = 30.0
) -> None:
    """
    _handle_generate_title_card() now starts a background QThread and
    returns immediately (real-world finding, 2026-10-01: the previous
    synchronous version froze the whole app for the length of a real
    FFmpeg pass) - every test asserting on its outcome must pump the Qt
    event loop until the worker's queued finished/failed and
    thread.finished signals have actually been delivered.
    """

    deadline = time.monotonic() + timeout_seconds

    while view._title_card_threads or view._generating_title_card_job_ids:
        if time.monotonic() > deadline:
            raise TimeoutError("Title card generation never completed.")

        qapp.processEvents()
        time.sleep(0.01)

    assert view.wait_for_pending_generations(timeout_ms=10_000)


def _generate_button(view: PackagingView) -> QPushButton | None:
    return next(
        (
            b
            for b in view.findChildren(QPushButton)
            if b.text() == "Generate title card onto the render"
        ),
        None,
    )


def test_no_generate_button_when_title_card_is_disabled(
    qapp: QApplication, tmp_path: Path
) -> None:
    fake_service = _FakeOpeningTitleCardService(
        result=RenderResult(
            success=True,
            output_file="outputs/main_render_with_title_card.mp4",
            render_engine="ffmpeg",
            duration_seconds=63,
            status=RenderStatus.COMPLETED,
        )
    )

    view = _view(tmp_path=tmp_path, opening_title_card_service=fake_service)
    job = _job(title_card_enabled=False)

    view._job_store.add(job)
    view._job_store.set_render_result(job.id, _successful_render_result(job))
    view.set_job(job.id)
    view.refresh(job)

    assert _generate_button(view) is None


def test_no_generate_button_without_a_successful_render(
    qapp: QApplication, tmp_path: Path
) -> None:
    fake_service = _FakeOpeningTitleCardService(
        result=RenderResult(
            success=True,
            output_file="outputs/main_render_with_title_card.mp4",
            render_engine="ffmpeg",
            duration_seconds=63,
            status=RenderStatus.COMPLETED,
        )
    )

    view = _view(tmp_path=tmp_path, opening_title_card_service=fake_service)
    job = _job(title_card_enabled=True)

    view._job_store.add(job)
    view.set_job(job.id)
    view.refresh(job)

    assert _generate_button(view) is None


def test_no_generate_button_without_an_uploaded_background_image(
    qapp: QApplication, tmp_path: Path
) -> None:
    """
    Real-world finding, 2026-09-30: no real AI image-generation
    provider exists anywhere in this app - auto-generate (the fallback
    whenever no image is uploaded) always fell through to
    DryRunThumbnailImageProvider's fake "dry-run://..." placeholder,
    which FFmpeg cannot open ("Protocol not found"), crashing every
    real attempt. The button is hidden instead of left to crash -
    confirmed live.
    """

    fake_service = _FakeOpeningTitleCardService(
        result=RenderResult(
            success=True,
            output_file="outputs/main_render_with_title_card.mp4",
            render_engine="ffmpeg",
            duration_seconds=63,
            status=RenderStatus.COMPLETED,
        )
    )

    view = _view(tmp_path=tmp_path, opening_title_card_service=fake_service)
    job = _job(title_card_enabled=True)
    assert not job.title_card_image_path

    view._job_store.add(job)
    view._job_store.set_render_result(job.id, _successful_render_result(job))
    view.set_job(job.id)
    view.refresh(job)

    assert _generate_button(view) is None


def test_generate_handler_is_a_no_op_without_an_uploaded_background_image(
    qapp: QApplication, tmp_path: Path
) -> None:
    """
    Defense in depth for the same real finding - even if
    _handle_generate_title_card were somehow invoked directly (not
    just gated by the button's own visibility), it must never call
    through to a crash-prone auto-generate.
    """

    fake_service = _FakeOpeningTitleCardService(
        result=RenderResult(
            success=True,
            output_file="outputs/main_render_with_title_card.mp4",
            render_engine="ffmpeg",
            duration_seconds=63,
            status=RenderStatus.COMPLETED,
        )
    )

    view = _view(tmp_path=tmp_path, opening_title_card_service=fake_service)
    job = _job(title_card_enabled=True)

    view._job_store.add(job)
    view._job_store.set_render_result(job.id, _successful_render_result(job))
    view.set_job(job.id)
    view.refresh(job)

    view._handle_generate_title_card()

    assert fake_service.calls == []


def test_no_generate_button_when_service_is_not_configured(
    qapp: QApplication, tmp_path: Path
) -> None:
    view = _view(tmp_path=tmp_path, opening_title_card_service=None)
    job = _job(title_card_enabled=True)

    view._job_store.add(job)
    view._job_store.set_render_result(job.id, _successful_render_result(job))
    view.set_job(job.id)
    view.refresh(job)

    assert _generate_button(view) is None


def test_clicking_generate_replaces_the_stored_render_result(
    qapp: QApplication, tmp_path: Path
) -> None:
    on_change_calls: list[bool] = []

    final_file = "outputs/main_render_with_title_card.mp4"

    fake_service = _FakeOpeningTitleCardService(
        result=RenderResult(
            success=True,
            output_file=final_file,
            render_engine="ffmpeg",
            duration_seconds=63,
            status=RenderStatus.COMPLETED,
        )
    )

    view = _view(
        on_change=lambda: on_change_calls.append(True),
        tmp_path=tmp_path,
        opening_title_card_service=fake_service,
    )
    job = _job(title_card_enabled=True)
    # Real-world finding, 2026-09-30: auto-generate (no uploaded image)
    # always crashed FFmpeg for real - "Generate title card onto the
    # render" is now hidden unless a real background image is set.
    job.title_card_image_path = "C:/Users/Test/background.jpg"
    job.title_card_text = "My Own Title"
    job.title_card_text_position = ThumbnailTextPosition.BOTTOM

    view._job_store.add(job)
    view._job_store.set_render_result(job.id, _successful_render_result(job))
    view.set_job(job.id)
    view.refresh(job)

    generate_button = _generate_button(view)
    assert generate_button is not None

    generate_button.click()
    _wait_for_generation(view, qapp)

    assert len(fake_service.calls) == 1
    assert fake_service.calls[0]["main_video_file"] == "outputs/main_render.mp4"
    # The real fix this test also locks in: the uploaded image path is
    # actually threaded through now, not silently ignored.
    assert fake_service.calls[0]["image_override"] == "C:/Users/Test/background.jpg"
    # Real-world regression, 2026-10-02: the saved title text/position
    # were never passed on, so the card always showed the auto title.
    assert fake_service.calls[0]["title_override"] == "My Own Title"
    assert fake_service.calls[0]["position_override"] == ThumbnailTextPosition.BOTTOM

    stored = view._job_store.get_render_result(job.id)
    assert stored is not None
    assert stored.render_result is not None
    assert stored.render_result.output_file == final_file
    assert on_change_calls == [True]


def test_generated_title_card_result_reloads_from_disk_in_a_fresh_store(
    qapp: QApplication, tmp_path: Path
) -> None:
    """
    Real-world regression, 2026-10-02: generation saved a result whose
    nested render_result no longer matched its embedded job snapshot.
    InMemoryJobStore and JsonJobStore's own cache hid that until the next
    app launch, when the file failed validation and the project could no
    longer be opened. This goes through a real JsonJobStore and reads the
    result back through a brand-new one, like a restart does.
    """

    final_file = "outputs/main_render_with_title_card.mp4"
    fake_service = _FakeOpeningTitleCardService(
        result=RenderResult(
            success=True,
            output_file=final_file,
            render_engine="ffmpeg",
            duration_seconds=63,
            status=RenderStatus.COMPLETED,
        )
    )
    store_root = tmp_path / "store"
    view = PackagingView(
        job_store=JsonJobStore(storage_root=store_root),
        seo_package_service=None,  # type: ignore[arg-type]
        thumbnail_package_service=None,  # type: ignore[arg-type]
        final_export_service=FinalExportService(export_root=tmp_path / "exports"),
        on_change=lambda: None,
        opening_title_card_service=fake_service,
    )
    job = _job(title_card_enabled=True)
    job.title_card_image_path = "C:/Users/Test/background.jpg"
    # A real rendered job carries these (VideoJob requires them whenever
    # render_result is set) - without them the embedded job snapshot in
    # the persisted result could never be reloaded, for any reason.
    job.scenes = [
        Scene(
            scene_number=1,
            title="Scene 1",
            narration="Narration.",
            visual_prompt="Visual.",
            estimated_duration_seconds=8,
        )
    ]
    job.voice_file = "dry-run://voice/test.mp3"
    job.audio_timeline = AudioTimeline()
    job.video_clips = [
        VideoClip(
            scene_number=1,
            source_type=SceneSourceType.MANUAL_UPLOAD,
            duration_seconds=8,
            local_file="/data/manual_uploads/scene_1.mp4",
        )
    ]
    job.video_timeline = VideoTimeline()

    view._job_store.add(job)
    view._job_store.set_render_result(job.id, _successful_render_result(job))
    job.render_result = _successful_render_result(job).render_result
    view.set_job(job.id)
    view.refresh(job)

    generate_button = _generate_button(view)
    assert generate_button is not None
    generate_button.click()
    _wait_for_generation(view, qapp)

    reloaded = JsonJobStore(storage_root=store_root).get_render_result(job.id)

    assert reloaded is not None
    assert reloaded.render_result is not None
    assert reloaded.render_result.output_file == final_file
    assert reloaded.job.render_result is not None
    assert reloaded.job.render_result.output_file == final_file


def test_generation_failure_records_an_error_and_leaves_render_result_unchanged(
    qapp: QApplication, tmp_path: Path
) -> None:
    fake_service = _FakeOpeningTitleCardService(
        result=RenderResult(
            success=False,
            output_file=None,
            render_engine="ffmpeg",
            duration_seconds=0,
            status=RenderStatus.FAILED,
            error_message="Simulated title card failure.",
        )
    )

    view = _view(tmp_path=tmp_path, opening_title_card_service=fake_service)
    job = _job(title_card_enabled=True)
    job.title_card_image_path = "C:/Users/Test/background.jpg"

    view._job_store.add(job)
    view._job_store.set_render_result(job.id, _successful_render_result(job))
    view.set_job(job.id)
    view.refresh(job)

    generate_button = _generate_button(view)
    assert generate_button is not None

    # A real failure here routes into show_recoverable_error(), a real
    # blocking QMessageBox under headless Qt - patched out the same
    # way every other error-path test in this codebase already does
    # (see test_clip_workspace_view_scene_generation.py's own
    # precedent), matching the documented qt_error_dialog_test_hang
    # pattern.
    with patch("src.desktop.views.packaging_view.show_recoverable_error"):
        generate_button.click()
        _wait_for_generation(view, qapp)

    stored = view._job_store.get_render_result(job.id)
    assert stored is not None
    assert stored.render_result is not None
    assert stored.render_result.output_file == "outputs/main_render.mp4"

    stored_job = view._job_store.get(job.id)
    assert stored_job is not None
    assert any("Simulated title card failure." in error for error in stored_job.errors)


class _BlockingTitleCardService:
    """
    Blocks inside build() until released or cancelled - proves the
    handler returns immediately (GUI thread stays free) and that Stop
    reaches the real cancellation_check the service is handed.
    """

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.saw_cancellation = False
        self.progress_callback_received = False

    def build(self, **kwargs: object) -> RenderResult:
        self.progress_callback_received = callable(kwargs.get("progress_callback"))
        cancellation_check = kwargs["cancellation_check"]
        assert callable(cancellation_check)

        self.started.set()

        deadline = time.monotonic() + 20.0

        while time.monotonic() < deadline:
            if cancellation_check():
                self.saw_cancellation = True

                return RenderResult(
                    success=False,
                    output_file=None,
                    render_engine="ffmpeg",
                    duration_seconds=0,
                    status=RenderStatus.FAILED,
                    error_message="FFmpeg render was cancelled.",
                )

            if self.release.is_set():
                break

            time.sleep(0.01)

        return RenderResult(
            success=True,
            output_file="outputs/main_render_with_title_card.mp4",
            render_engine="ffmpeg",
            duration_seconds=63,
            status=RenderStatus.COMPLETED,
        )


def _prepared_blocking_view(
    tmp_path: Path,
) -> tuple[PackagingView, VideoJob, _BlockingTitleCardService]:
    service = _BlockingTitleCardService()
    job = _job(title_card_enabled=True)
    holder: dict[str, PackagingView] = {}

    # Mirrors the real app: every workspace's on_change refreshes all
    # workspaces, which is what restores the Generate button once a
    # generation ends.
    view = _view(
        on_change=lambda: holder["view"].refresh(job),
        tmp_path=tmp_path,
        opening_title_card_service=service,
    )
    holder["view"] = view
    job.title_card_image_path = "C:/Users/Test/background.jpg"

    view._job_store.add(job)
    view._job_store.set_render_result(job.id, _successful_render_result(job))
    view.set_job(job.id)
    view.refresh(job)

    return view, job, service


def _wait_until(qapp: QApplication, predicate: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 10.0

    while not predicate():
        if time.monotonic() > deadline:
            raise TimeoutError("Condition never became true.")

        qapp.processEvents()
        time.sleep(0.01)


def _flush_deferred_deletes(qapp: QApplication) -> None:
    """
    refresh()/_rebuild_all() only queue the old widgets for deletion
    (deleteLater) - until Qt actually processes those deferred
    deletes, findChildren() still returns the stale, about-to-be-
    destroyed buttons alongside the newly built ones.
    """

    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _button_texts(view: PackagingView) -> list[str]:
    return [b.text() for b in view.findChildren(QPushButton)]


def test_generation_runs_in_the_background_and_shows_progress_with_a_stop_button(
    qapp: QApplication, tmp_path: Path
) -> None:
    """
    Real-world finding, 2026-10-01: generation used to run
    synchronously on the GUI thread - Windows reported the whole app
    "Not Responding" for the length of a real FFmpeg pass. The click
    handler must return immediately, with the Generate button replaced
    by a progress state and a Stop button.
    """

    view, job, service = _prepared_blocking_view(tmp_path)

    _generate_button(view).click()  # type: ignore[union-attr]

    # Reaching this line at all (with the worker still blocked inside
    # build()) proves the handler did not run the pass synchronously.
    assert job.id in view._generating_title_card_job_ids
    _flush_deferred_deletes(qapp)
    assert _generate_button(view) is None
    assert "Stop" in _button_texts(view)
    assert view._title_card_progress_bar.value() == 0

    _wait_until(qapp, service.started.is_set)
    assert service.progress_callback_received

    service.release.set()
    _wait_for_generation(view, qapp)

    assert job.id not in view._generating_title_card_job_ids
    assert _generate_button(view) is not None


def test_stop_cancels_the_in_flight_generation_and_restores_the_generate_button(
    qapp: QApplication, tmp_path: Path
) -> None:
    view, job, service = _prepared_blocking_view(tmp_path)

    _generate_button(view).click()  # type: ignore[union-attr]
    _wait_until(qapp, service.started.is_set)

    stop_button = next(b for b in view.findChildren(QPushButton) if b.text() == "Stop")

    with patch("src.desktop.views.packaging_view.show_recoverable_error"):
        stop_button.click()
        _wait_for_generation(view, qapp)

    assert service.saw_cancellation
    assert job.id not in view._generating_title_card_job_ids

    stored = view._job_store.get_render_result(job.id)
    assert stored is not None
    assert stored.render_result is not None
    assert stored.render_result.output_file == "outputs/main_render.mp4"
    # Restart is just clicking Generate again - the button is back.
    assert _generate_button(view) is not None


def test_close_path_cancels_and_joins_pending_generations(
    qapp: QApplication, tmp_path: Path
) -> None:
    view, _job_obj, service = _prepared_blocking_view(tmp_path)

    _generate_button(view).click()  # type: ignore[union-attr]
    _wait_until(qapp, service.started.is_set)

    assert view.has_pending_generations()

    with patch("src.desktop.views.packaging_view.show_recoverable_error"):
        view.cancel_pending_generations()

        assert view.wait_for_pending_generations(timeout_ms=10_000)

    assert service.saw_cancellation
    assert not view.has_pending_generations()


def _clip_view(
    qapp: QApplication, tmp_path: Path, *, service: object | None = None
) -> tuple[PackagingView, VideoJob]:
    view = _view(tmp_path=tmp_path, opening_title_card_service=service)
    job = _job(title_card_enabled=True)
    view._job_store.add(job)
    view._job_store.set_render_result(job.id, _successful_render_result(job))
    view.set_job(job.id)
    view.refresh(job)
    _flush_deferred_deletes(qapp)

    return view, job


def _last_button(view: PackagingView, text: str) -> QPushButton:
    return [b for b in view.findChildren(QPushButton) if b.text() == text][-1]


def _first_button(view: PackagingView, text: str) -> QPushButton:
    # The Export variants card below also has "Upload my own image..." /
    # "Upload my own clip..." buttons - the title card's own are first.
    return next(b for b in view.findChildren(QPushButton) if b.text() == text)


def _title_card_displays(view: PackagingView) -> tuple[QLineEdit, QLineEdit]:
    image = next(
        e
        for e in view.findChildren(QLineEdit)
        if e.placeholderText() == "Auto-generate a dedicated AI image (default)"
    )
    clip = next(
        e
        for e in view.findChildren(QLineEdit)
        if e.placeholderText() == "No clip - a title card is generated"
    )

    return image, clip


def _title_input(view: PackagingView) -> QLineEdit:
    return next(
        e
        for e in view.findChildren(QLineEdit)
        if e.placeholderText().startswith("Auto: ")
    )


def _position_combo(view: PackagingView) -> QComboBox:
    return next(
        c for c in view.findChildren(QComboBox) if c.findText("Auto (center)") >= 0
    )


def _pick_clip(view: PackagingView, path: str = "C:/brand/intro.mp4") -> None:
    with patch(
        "src.desktop.views.packaging_view.QFileDialog.getOpenFileName",
        return_value=(path, ""),
    ):
        _first_button(view, "Upload my own clip...").click()


def test_choosing_a_clip_greys_out_the_title_fields_and_clears_the_image(
    qapp: QApplication, tmp_path: Path
) -> None:
    view, job = _clip_view(qapp, tmp_path)
    job.title_card_image_path = "C:/brand/bg.png"
    view.refresh(job)
    _flush_deferred_deletes(qapp)

    image, clip = _title_card_displays(view)
    assert image.text() == "C:/brand/bg.png"
    assert _title_input(view).isEnabled() is True

    _pick_clip(view)

    assert clip.text() == "C:/brand/intro.mp4"
    assert image.text() == ""
    assert _title_input(view).isEnabled() is False
    assert _position_combo(view).isEnabled() is False


def test_choosing_an_image_drops_a_previously_chosen_clip(
    qapp: QApplication, tmp_path: Path
) -> None:
    view, _job_ = _clip_view(qapp, tmp_path)
    _pick_clip(view)

    with patch(
        "src.desktop.views.packaging_view.QFileDialog.getOpenFileName",
        return_value=("C:/brand/bg.png", ""),
    ):
        _first_button(view, "Upload my own image...").click()

    image, clip = _title_card_displays(view)

    assert image.text() == "C:/brand/bg.png"
    assert clip.text() == ""
    assert _title_input(view).isEnabled() is True


def test_cancelling_the_clip_dialog_changes_nothing(
    qapp: QApplication, tmp_path: Path
) -> None:
    view, job = _clip_view(qapp, tmp_path)
    job.title_card_image_path = "C:/brand/bg.png"
    view.refresh(job)
    _flush_deferred_deletes(qapp)

    _pick_clip(view, path="")

    image, clip = _title_card_displays(view)

    assert image.text() == "C:/brand/bg.png"
    assert clip.text() == ""


def test_auto_generate_clears_both_sources(qapp: QApplication, tmp_path: Path) -> None:
    view, _job_ = _clip_view(qapp, tmp_path)
    _pick_clip(view)

    _last_button(view, "Auto-generate image").click()

    image, clip = _title_card_displays(view)

    assert image.text() == "" and clip.text() == ""
    assert _title_input(view).isEnabled() is True


def test_saving_a_clip_persists_it_and_drops_the_image_path(
    qapp: QApplication, tmp_path: Path
) -> None:
    view, job = _clip_view(qapp, tmp_path)
    job.title_card_image_path = "C:/brand/bg.png"
    view.refresh(job)
    _flush_deferred_deletes(qapp)

    _pick_clip(view)
    _last_button(view, "Save title card settings").click()

    assert job.title_card_clip_path == "C:/brand/intro.mp4"
    assert job.title_card_image_path is None


def test_a_saved_clip_is_applied_without_any_background_image(
    qapp: QApplication, tmp_path: Path
) -> None:
    """The apply button must be offered, and the clip handed to the
    service, with no background image set at all - and nothing is
    generated, so title text/position are not what drives it."""

    fake_service = _FakeOpeningTitleCardService(
        result=RenderResult(
            success=True,
            output_file="outputs/main_render_with_title_card.mp4",
            render_engine="ffmpeg",
            duration_seconds=63,
            status=RenderStatus.COMPLETED,
        )
    )
    view, job = _clip_view(qapp, tmp_path, service=fake_service)
    job.title_card_clip_path = "C:/brand/intro.mp4"
    view.refresh(job)
    _flush_deferred_deletes(qapp)

    button = _last_button(view, "Add my clip to the render")
    button.click()
    _wait_for_generation(view, qapp)

    assert len(fake_service.calls) == 1
    assert fake_service.calls[0]["title_clip_override"] == "C:/brand/intro.mp4"
    assert fake_service.calls[0]["image_override"] is None


def test_a_clip_is_applied_even_when_no_seo_context_can_be_built(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Live, 2026-10-07: a project with no research could not add its own title
    clip - "SEO context requires a VideoJob with research" - although a clip
    needs no SEO text at all."""

    class _NoContextBuilder:
        def build(self, *args: object, **kwargs: object) -> object:
            raise ValueError("SEO context requires a VideoJob with research.")

    monkeypatch.setattr(
        "src.desktop.views.packaging_view.SEOContextBuilder", _NoContextBuilder
    )
    fake_service = _FakeOpeningTitleCardService(
        result=RenderResult(
            success=True,
            output_file="outputs/main_render_with_title_card.mp4",
            render_engine="ffmpeg",
            duration_seconds=63,
            status=RenderStatus.COMPLETED,
        )
    )
    view, job = _clip_view(qapp, tmp_path, service=fake_service)
    job.title_card_clip_path = "C:/brand/intro.mp4"
    view.refresh(job)
    _flush_deferred_deletes(qapp)

    _last_button(view, "Add my clip to the render").click()
    _wait_for_generation(view, qapp)

    assert len(fake_service.calls) == 1
    assert fake_service.calls[0]["seo_context"] is None
    assert job.errors == []


def test_without_a_clip_or_image_the_apply_button_is_still_hidden(
    qapp: QApplication, tmp_path: Path
) -> None:
    view, _job_ = _clip_view(
        qapp,
        tmp_path,
        service=_FakeOpeningTitleCardService(
            result=_successful_render_result(_job()).render_result  # type: ignore[arg-type]
        ),
    )

    assert not [
        b
        for b in view.findChildren(QPushButton)
        if b.text()
        in {"Add my clip to the render", "Generate title card onto the render"}
    ]


def test_applying_the_title_card_again_builds_from_the_original_render(
    qapp: QApplication, tmp_path: Path
) -> None:
    """
    Real-world regression, 2026-10-03: after one successful apply the
    stored render result points at the with-title-card file. Applying
    again (e.g. after correcting the title) used THAT as its input and
    stacked a second card on the first. It must always start from the
    original, card-free render (VideoJob.render_result).
    """

    fake_service = _FakeOpeningTitleCardService(
        result=RenderResult(
            success=True,
            output_file="outputs/main_render_with_title_card.mp4",
            render_engine="ffmpeg",
            duration_seconds=63,
            status=RenderStatus.COMPLETED,
        )
    )
    view = _view(tmp_path=tmp_path, opening_title_card_service=fake_service)
    job = _job(title_card_enabled=True)
    job.title_card_image_path = "C:/Users/Test/background.jpg"
    job.scenes = [
        Scene(
            scene_number=1,
            title="Scene 1",
            narration="Narration.",
            visual_prompt="Visual.",
            estimated_duration_seconds=8,
        )
    ]
    job.voice_file = "dry-run://voice/test.mp3"
    job.audio_timeline = AudioTimeline()
    job.video_clips = [
        VideoClip(
            scene_number=1,
            source_type=SceneSourceType.MANUAL_UPLOAD,
            duration_seconds=8,
            local_file="/data/manual_uploads/scene_1.mp4",
        )
    ]
    job.video_timeline = VideoTimeline()
    # The original, card-free render the job itself carries...
    original_render = _successful_render_result(job).render_result
    job.render_result = original_render

    # ...while the store already holds the result of a previous apply.
    base_orchestration = RenderOrchestrationResult(
        success=True,
        status=JobStatus.COMPLETED,
        current_stage=WorkflowStage.READY_FOR_UPLOAD,
        job=job,
        render_result=original_render,
    )
    already_applied = replace_orchestration_render_result(
        base_orchestration,
        RenderResult(
            success=True,
            output_file="outputs/main_render_with_title_card.mp4",
            render_engine="ffmpeg",
            duration_seconds=63,
            status=RenderStatus.COMPLETED,
        ),
    )
    view._job_store.add(job)
    view._job_store.set_render_result(job.id, already_applied)
    view.set_job(job.id)
    view.refresh(job)

    generate_button = _generate_button(view)
    assert generate_button is not None
    generate_button.click()
    _wait_for_generation(view, qapp)

    call = fake_service.calls[0]

    assert call["main_video_file"] == "outputs/main_render.mp4"
    assert (
        str(call["output_file"])
        .replace("\\", "/")
        .endswith("main_render_with_title_card.mp4")
    )
    assert "with_title_card_with_title_card" not in str(call["output_file"])
