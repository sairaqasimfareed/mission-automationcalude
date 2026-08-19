from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402
from uuid import uuid4  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.desktop.job_store import InMemoryJobStore  # noqa: E402
from src.desktop.views.content_studio_view import (  # noqa: E402
    _CI_STAGES,
    ContentStudioView,
)
from src.models.video_job import VideoJob  # noqa: E402
from src.services.content_intelligence_pipeline import (  # noqa: E402
    ContentIntelligencePipeline,
)
from src.services.content_pipeline import ContentPipeline  # noqa: E402
from src.services.llm.llm_service import LLMServiceResult  # noqa: E402
from src.shared.llm.models import (  # noqa: E402
    LLMCallResult,
    LLMCallStatus,
    LLMProvider,
)
from src.shared.llm.request import LLMRequest  # noqa: E402


class _EchoStubLLMService:
    """Mirrors test_content_intelligence_pipeline.py's stub - echoes
    each request's own dry_run_response so every retrofitted service's
    parser accepts it."""

    def generate(
        self,
        request: LLMRequest,
        *,
        estimated_cost_usd: float = 0.0,
        profile_ids: list[str] | None = None,
    ) -> LLMServiceResult:
        content = request.dry_run_response or (
            "The Mary Celeste was found adrift, seaworthy, with no crew aboard."
        )

        result = LLMCallResult(
            status=LLMCallStatus.SUCCESS,
            provider=LLMProvider.OPENAI,
            model="test-model",
            content=content,
        )

        return LLMServiceResult(
            result=result,
            selected_profile_id="test-profile",
            all_providers_failed=False,
        )


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])

    yield app  # type: ignore[misc]


def _view(job_store: InMemoryJobStore) -> ContentStudioView:
    stub = _EchoStubLLMService()

    return ContentStudioView(
        job_store=job_store,
        content_pipeline=ContentPipeline(llm_service=stub),  # type: ignore[arg-type]
        content_intelligence_pipeline=ContentIntelligencePipeline(
            llm_service=stub  # type: ignore[arg-type]
        ),
        on_change=lambda: None,
    )


def _job() -> VideoJob:
    return VideoJob(
        project_name="Mary Celeste Documentary",
        channel_name="Maritime Mysteries",
        niche="unsolved maritime disappearances",
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        target_duration_seconds=180,
        target_audience="mystery enthusiasts",
    )


def test_refresh_builds_without_error_before_any_stage_runs(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)  # must not raise


def test_selecting_a_stage_updates_the_selected_index(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    assert view._selected_ci_stage_index == 0

    view._handle_select_ci_stage(3)

    assert view._selected_ci_stage_index == 3


def test_run_audience_promise_stage_populates_job(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_run_ci_stage("audience_promise")

    assert job.audience_promise is not None
    assert job.editorial_profile_snapshot is not None


def test_running_stages_in_order_reaches_a_generated_script(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    for stage_key, _label in _CI_STAGES:
        view._handle_run_ci_stage(stage_key)
        view.refresh(job)

    assert job.generated_script is not None
    assert not job.errors


def test_running_a_stage_out_of_order_records_an_error_not_a_crash(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # QMessageBox.warning() opens a real modal dialog and blocks
    # forever under the offscreen Qt platform (no display to dismiss
    # it) - same guard test_desktop_app_integration.py's
    # no_blocking_dialogs fixture applies for every other view.
    monkeypatch.setattr(
        "src.desktop.views.content_studio_view.QMessageBox.warning",
        lambda *args, **kwargs: None,
    )

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    # Script requires every upstream stage - none have run yet.
    view._handle_run_ci_stage("script")

    assert job.generated_script is None
    assert len(job.errors) == 1
    assert "Content Intelligence stage failed" in job.errors[0]


def test_unknown_job_id_does_not_crash_stage_handlers(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    view = _view(job_store)
    view.set_job(uuid4())

    view._handle_run_ci_stage("audience_promise")  # must not raise
