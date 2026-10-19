"""
Stop render (2026-10-19). The Render tab had no way to stop a render, and the render pipeline above FFmpeg has no
cancellation path of its own - a render killed by the one-hour limit was simply started again from the beginning.
A process-wide stop now ends every FFmpeg run at its next check (the automatic retries included) until the next
render clears it.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from src.models.ffmpeg_execution_result import FFmpegExecutionStatus
from src.services.ffmpeg_execution_service import clear_cancel_all, request_cancel_all
from tests.test_ffmpeg_execution_service import (
    ScriptedExecutionService,
    build_command_plan,
)

_SLOW = (
    "import time;"
    "print('out_time_us=100000', flush=True);"
    "print('progress=continue', flush=True);"
    "time.sleep(20)"
)


def _run():  # type: ignore[no-untyped-def]
    with tempfile.TemporaryDirectory() as folder:
        service = ScriptedExecutionService(_SLOW, terminate_grace_seconds=0.5)

        return service.execute(
            build_command_plan(Path(folder) / "out.mp4"), total_duration_seconds=10.0
        )


def test_the_stop_request_ends_a_running_render_as_cancelled() -> None:
    request_cancel_all()

    try:
        result = _run()
    finally:
        clear_cancel_all()

    assert result.success is False
    assert result.status == FFmpegExecutionStatus.CANCELLED
    assert result.error_message is not None and "cancel" in result.error_message.lower()


def test_clearing_the_stop_lets_the_next_render_run_normally() -> None:
    request_cancel_all()
    clear_cancel_all()

    with tempfile.TemporaryDirectory() as folder:
        quick = ScriptedExecutionService(
            "print('out_time_us=1000000', flush=True);print('progress=end', flush=True)",
            terminate_grace_seconds=0.5,
        )
        result = quick.execute(
            build_command_plan(Path(folder) / "ok.mp4"), total_duration_seconds=1.0
        )

    assert result.status != FFmpegExecutionStatus.CANCELLED


def test_the_render_tab_shows_a_stop_button_while_rendering() -> None:
    from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget

    from src.desktop.job_store import InMemoryJobStore
    from src.desktop.views.render_workspace_view import RenderWorkspaceView
    from tests.test_render_workspace_view_output_resolution import (
        _FakeRenderRuntimeFactory,
    )

    _app = QApplication.instance() or QApplication([])
    view = RenderWorkspaceView(
        job_store=InMemoryJobStore(),
        render_runtime_factory=_FakeRenderRuntimeFactory(),  # type: ignore[arg-type]
        asset_workflow_service=object(),  # type: ignore[arg-type]
        on_change=lambda: None,
    )
    holder = QWidget()
    view._build_render_progress_state(QVBoxLayout(holder))  # noqa: SLF001
    buttons = {b.text(): b for b in holder.findChildren(QPushButton)}

    assert "Stop render" in buttons and buttons["Stop render"].isEnabled()
    assert buttons["Run render"].isEnabled() is False

    buttons["Stop render"].click()
    try:
        from src.services.ffmpeg_execution_service import _CANCEL_ALL

        assert _CANCEL_ALL.is_set()
    finally:
        clear_cancel_all()
