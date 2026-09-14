from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QComboBox  # noqa: E402

from src.desktop.job_store import InMemoryJobStore  # noqa: E402
from src.desktop.views.render_workspace_view import (  # noqa: E402
    RenderWorkspaceView,
)
from src.models.video_job import VideoJob  # noqa: E402


class _StopBeforeRender(Exception):
    """
    Deliberately NOT a RuntimeError/ValueError - _execute_render only
    catches those two (to show a recoverable-error dialog), so this
    propagates straight out to the test instead, letting the test stop
    right after build() records its kwargs without ever reaching the
    QMessageBox dialog path or starting a real QThread.
    """


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])

    yield app  # type: ignore[misc]


class _FakeRenderRuntimeFactory:
    """
    Records the exact keyword arguments RenderWorkspaceView._execute_render
    passes into ProjectRenderRuntimeFactory.build() - real-world finding,
    2026-09-14: output_resolution used to be silently left at every
    layer's own hardcoded "1920x1080" default, with no caller anywhere
    ever overriding it. This stands in for the real factory (which needs
    real voice/provider infrastructure to construct) so the test can
    assert on exactly what RenderWorkspaceView requested, without
    needing a real render to actually run.
    """

    def __init__(self) -> None:
        self.build_calls: list[dict[str, object]] = []

    def build(self, **kwargs: object) -> object:
        self.build_calls.append(kwargs)

        raise _StopBeforeRender


def _job(*, output_resolution: str = "1920x1080") -> VideoJob:
    return VideoJob(
        project_name="Test Project",
        channel_name="Test Channel",
        niche="test niche",
        topic="Test topic",
        output_resolution=output_resolution,
    )


def _view(
    job_store: InMemoryJobStore,
) -> tuple[RenderWorkspaceView, _FakeRenderRuntimeFactory]:
    factory = _FakeRenderRuntimeFactory()
    view = RenderWorkspaceView(
        job_store=job_store,
        render_runtime_factory=factory,  # type: ignore[arg-type]
        asset_workflow_service=object(),  # type: ignore[arg-type]
        on_change=lambda: None,
    )

    return view, factory


def test_output_resolution_defaults_to_the_jobs_current_value(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job(output_resolution="1280x720")
    job_store.add(job)

    view, _ = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    combos = view.findChildren(QComboBox)
    resolution_combo = next(c for c in combos if c.currentData() is not None)

    assert resolution_combo.currentData() == "1280x720"


def test_changing_the_output_resolution_updates_the_job(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    job = _job(output_resolution="1920x1080")
    job_store.add(job)

    changes: list[None] = []
    factory = _FakeRenderRuntimeFactory()
    view = RenderWorkspaceView(
        job_store=job_store,
        render_runtime_factory=factory,  # type: ignore[arg-type]
        asset_workflow_service=object(),  # type: ignore[arg-type]
        on_change=lambda: changes.append(None),
    )
    view.set_job(job.id)
    view.refresh(job)

    combos = view.findChildren(QComboBox)
    resolution_combo = next(c for c in combos if c.currentData() is not None)

    target_index = next(
        i
        for i in range(resolution_combo.count())
        if resolution_combo.itemData(i) == "3840x2160"
    )
    resolution_combo.setCurrentIndex(target_index)

    assert job.output_resolution == "3840x2160"
    assert changes  # on_change was called


def test_execute_render_passes_the_jobs_output_resolution_to_the_factory(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job(output_resolution="2560x1440")
    job.scenes = []  # irrelevant to this test - build() is called regardless
    job_store.add(job)

    view, factory = _view(job_store)
    view.set_job(job.id)

    with pytest.raises(_StopBeforeRender):
        view._execute_render(job)

    assert len(factory.build_calls) == 1
    assert factory.build_calls[0]["output_resolution"] == "2560x1440"
