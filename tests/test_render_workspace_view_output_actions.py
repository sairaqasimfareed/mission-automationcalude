"""
REQ-0A (Render Download/Review Gate), 2026-09-21: once a render
succeeds, the workspace only ever showed a plain text output-file
label with no action at all - the user had to manually navigate the
filesystem to find and open it, and outputs/final_video.mp4 gets
silently overwritten by every subsequent render, so there was no way
to preserve a review copy before moving on. This file locks in the
three real actions added: Reveal in folder, Open in default player,
Save a copy as...
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest.mock import patch  # noqa: E402
from uuid import uuid4  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from src.desktop.job_store import InMemoryJobStore  # noqa: E402
from src.desktop.views.render_workspace_view import (  # noqa: E402
    RenderWorkspaceView,
)
from src.models.enums import JobStatus, WorkflowStage  # noqa: E402
from src.models.render_orchestration_result import (  # noqa: E402
    RenderOrchestrationResult,
)
from src.models.render_result import RenderResult, RenderStatus  # noqa: E402
from src.models.video_job import VideoJob  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])

    yield app  # type: ignore[misc]


def _job() -> VideoJob:
    return VideoJob(
        project_name="Test Project",
        channel_name="Test Channel",
        niche="test niche",
        topic="Test topic",
    )


def _render_result(*, output_file: str) -> RenderOrchestrationResult:
    job = _job()
    job.status = JobStatus.COMPLETED
    job.current_stage = WorkflowStage.READY_FOR_UPLOAD

    return RenderOrchestrationResult(
        success=True,
        status=JobStatus.COMPLETED,
        current_stage=WorkflowStage.READY_FOR_UPLOAD,
        completed_stages=[WorkflowStage.RENDER],
        job=job,
        render_result=RenderResult(
            success=True,
            output_file=output_file,
            render_engine="ffmpeg",
            render_time_seconds=1.0,
            duration_seconds=10,
            status=RenderStatus.COMPLETED,
        ),
    )


def _view_with_render_result(
    tmp_path: Path,
) -> tuple[RenderWorkspaceView, VideoJob, Path]:
    output_file = tmp_path / "outputs" / "final_video.mp4"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_bytes(b"synthetic mp4 bytes")

    job_store = InMemoryJobStore()
    job = _job()
    job.id = uuid4()
    job.scenes = []
    job_store.add(job)

    job_store.set_render_result(
        job.id,
        _render_result(output_file=output_file.as_posix()),
    )

    view = RenderWorkspaceView(
        job_store=job_store,
        render_runtime_factory=object(),  # type: ignore[arg-type]
        asset_workflow_service=object(),  # type: ignore[arg-type]
        on_change=lambda: None,
    )
    view.set_job(job.id)
    view.refresh(job)

    return view, job, output_file


def _buttons_by_text(view: RenderWorkspaceView) -> dict[str, QPushButton]:
    return {button.text(): button for button in view.findChildren(QPushButton)}


def test_render_output_actions_appear_after_a_successful_render(
    qapp: QApplication, tmp_path: Path
) -> None:
    view, _job, _output_file = _view_with_render_result(tmp_path)

    buttons = _buttons_by_text(view)

    assert "Reveal in folder" in buttons
    assert "Open in default player" in buttons
    assert "Save a copy as..." in buttons


def test_reveal_in_folder_opens_the_containing_directory(
    qapp: QApplication, tmp_path: Path
) -> None:
    view, _job, output_file = _view_with_render_result(tmp_path)

    with patch(
        "src.desktop.views.render_workspace_view.QDesktopServices.openUrl"
    ) as mock_open_url:
        _buttons_by_text(view)["Reveal in folder"].click()

    assert mock_open_url.call_count == 1
    opened_url = mock_open_url.call_args[0][0]
    assert Path(opened_url.toLocalFile()) == output_file.parent


def test_open_in_default_player_opens_the_file_itself(
    qapp: QApplication, tmp_path: Path
) -> None:
    view, _job, output_file = _view_with_render_result(tmp_path)

    with patch(
        "src.desktop.views.render_workspace_view.QDesktopServices.openUrl"
    ) as mock_open_url:
        _buttons_by_text(view)["Open in default player"].click()

    assert mock_open_url.call_count == 1
    opened_url = mock_open_url.call_args[0][0]
    assert opened_url.toLocalFile() == output_file.as_posix()


def test_save_a_copy_writes_the_real_file_to_the_chosen_destination(
    qapp: QApplication, tmp_path: Path
) -> None:
    view, _job, output_file = _view_with_render_result(tmp_path)

    destination = tmp_path / "reviews" / "copy.mp4"
    destination.parent.mkdir(parents=True, exist_ok=True)

    with patch(
        "src.desktop.views.render_workspace_view.QFileDialog.getSaveFileName",
        return_value=(str(destination), ""),
    ):
        _buttons_by_text(view)["Save a copy as..."].click()

    assert destination.is_file()
    assert destination.read_bytes() == output_file.read_bytes()


def test_save_a_copy_does_nothing_when_the_dialog_is_cancelled(
    qapp: QApplication, tmp_path: Path
) -> None:
    view, _job, _output_file = _view_with_render_result(tmp_path)

    with patch(
        "src.desktop.views.render_workspace_view.QFileDialog.getSaveFileName",
        return_value=("", ""),
    ):
        # Must not raise and must not attempt any copy.
        _buttons_by_text(view)["Save a copy as..."].click()

    assert not (tmp_path / "reviews").exists()


def test_save_a_copy_shows_a_recoverable_error_on_copy_failure(
    qapp: QApplication, tmp_path: Path
) -> None:
    view, _job, _output_file = _view_with_render_result(tmp_path)

    destination = tmp_path / "reviews" / "copy.mp4"

    with (
        patch(
            "src.desktop.views.render_workspace_view.QFileDialog.getSaveFileName",
            return_value=(str(destination), ""),
        ),
        patch(
            "src.desktop.views.render_workspace_view.shutil.copy2",
            side_effect=OSError("disk full"),
        ),
        patch(
            "src.desktop.views.render_workspace_view.show_recoverable_error"
        ) as mock_show_error,
    ):
        _buttons_by_text(view)["Save a copy as..."].click()

    assert mock_show_error.call_count == 1
