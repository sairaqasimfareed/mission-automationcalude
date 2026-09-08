from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from src.desktop.job_store import InMemoryJobStore  # noqa: E402
from src.desktop.views.quality_center_view import QualityCenterView  # noqa: E402
from src.models.google_flow_generation import (  # noqa: E402
    GoogleFlowGenerationAttempt,
    GoogleFlowGenerationRequest,
    GoogleFlowGenerationState,
    GoogleFlowStateTransition,
)
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


def test_readiness_card_shows_a_stuck_google_flow_attempt(qapp: QApplication) -> None:
    """
    MRA-PRE-7 (Pre-Installer Master Audit, GUI/operator-workflow
    audit) finding: job.flow_generation_attempts had zero GUI readers
    anywhere - proves the fix all the way through the real widget
    tree, not just at the ProductionReadinessService layer.
    """

    job_store = InMemoryJobStore()
    job = _job()
    job.flow_generation_attempts = [
        GoogleFlowGenerationAttempt(
            request=GoogleFlowGenerationRequest(
                scene_number=3,
                prompt="A dark hallway.",
                prompt_version="v1",
                profile_id="flow.default",
                idempotency_key="idempotency-key-1",
            ),
            state=GoogleFlowGenerationState.SUBMISSION_UNCERTAIN,
            state_history=[
                GoogleFlowStateTransition(state=GoogleFlowGenerationState.PLANNED),
                GoogleFlowStateTransition(
                    state=GoogleFlowGenerationState.SUBMISSION_UNCERTAIN
                ),
            ],
            profile_id="flow.default",
        ),
    ]
    job_store.add(job)

    view = QualityCenterView(job_store=job_store, on_change=lambda: None)
    view.set_job(job.id)
    view.refresh(job)

    labels = [label.text() for label in view.findChildren(QLabel)]

    assert any("scene 3" in text and "submission uncertain" in text for text in labels)
