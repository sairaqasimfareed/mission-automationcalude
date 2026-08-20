from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.desktop.job_store import InMemoryJobStore  # noqa: E402
from src.desktop.views.quality_center_view import QualityCenterView  # noqa: E402
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


def test_readiness_card_builds_without_error_for_a_bare_job(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = QualityCenterView(job_store=job_store, on_change=lambda: None)
    view.set_job(job.id)
    view.refresh(job)  # must not raise


def test_readiness_card_reflects_the_readiness_service(qapp: QApplication) -> None:
    from src.services.production_readiness_service import ProductionReadinessService

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = QualityCenterView(job_store=job_store, on_change=lambda: None)
    view.set_job(job.id)

    expected = ProductionReadinessService().evaluate(job)

    assert view._readiness_service.evaluate(job).state == expected.state
    assert len(view._readiness_service.evaluate(job).blockers) == len(expected.blockers)
