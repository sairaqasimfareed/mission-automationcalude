from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest.mock import patch  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from src.desktop.job_store import InMemoryJobStore  # noqa: E402
from src.desktop.views.packaging_view import PackagingView  # noqa: E402
from src.models.audience_promise import AudiencePromise, PromiseStrength  # noqa: E402
from src.models.enums import JobStatus, WorkflowStage  # noqa: E402
from src.models.render_orchestration_result import (  # noqa: E402
    RenderOrchestrationResult,
)
from src.models.render_result import RenderResult, RenderStatus  # noqa: E402
from src.models.research import ResearchResult, ResearchStatus  # noqa: E402
from src.models.script import Script, ScriptStatus  # noqa: E402
from src.models.video_job import VideoJob  # noqa: E402
from src.services.final_export.final_export_service import (  # noqa: E402
    FinalExportService,
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

    job.research = ResearchResult.model_construct(
        status=ResearchStatus.APPROVED,
        research_summary="Real research summary for the giant squid documentary.",
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

    view._job_store.add(job)
    view._job_store.set_render_result(job.id, _successful_render_result(job))
    view.set_job(job.id)
    view.refresh(job)

    generate_button = _generate_button(view)
    assert generate_button is not None

    generate_button.click()

    assert len(fake_service.calls) == 1
    assert fake_service.calls[0]["main_video_file"] == "outputs/main_render.mp4"

    stored = view._job_store.get_render_result(job.id)
    assert stored is not None
    assert stored.render_result is not None
    assert stored.render_result.output_file == final_file
    assert on_change_calls == [True]


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

    stored = view._job_store.get_render_result(job.id)
    assert stored is not None
    assert stored.render_result is not None
    assert stored.render_result.output_file == "outputs/main_render.mp4"

    stored_job = view._job_store.get(job.id)
    assert stored_job is not None
    assert any("Simulated title card failure." in error for error in stored_job.errors)
