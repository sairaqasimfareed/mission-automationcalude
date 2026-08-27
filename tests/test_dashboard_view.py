from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.desktop.job_store import InMemoryJobStore  # noqa: E402
from src.desktop.views.dashboard_view import DashboardView  # noqa: E402
from src.models.enums import Platform  # noqa: E402
from src.models.video_job import VideoJob  # noqa: E402
from src.services.pipeline_checkpoint_storage_service import (  # noqa: E402
    PipelineCheckpointStorageService,
)


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])

    yield app  # type: ignore[misc]


def _job(**overrides: object) -> VideoJob:
    base: dict[str, object] = dict(
        project_name="Deep Sea Documentary",
        channel_name="Ocean Channel",
        niche="ocean-life",
        topic="Deep sea creatures",
        platform=Platform.FACEBOOK,
    )
    base.update(overrides)
    return VideoJob(**base)


def _dashboard(tmp_path, job_store: InMemoryJobStore) -> DashboardView:
    return DashboardView(
        job_store=job_store,
        checkpoint_storage=PipelineCheckpointStorageService(
            storage_root=tmp_path / "checkpoints"
        ),
        on_open_project=lambda job_id: None,
    )


def test_refresh_shows_one_row_per_project(qapp: QApplication, tmp_path) -> None:
    job_store = InMemoryJobStore()
    job_store.add(_job())
    job_store.add(_job(project_name="Second Project"))
    dashboard = _dashboard(tmp_path, job_store)

    dashboard.refresh()

    assert dashboard._table.rowCount() == 2


def test_refresh_shows_the_project_name_and_platform(
    qapp: QApplication, tmp_path
) -> None:
    job_store = InMemoryJobStore()
    job_store.add(_job())
    dashboard = _dashboard(tmp_path, job_store)

    dashboard.refresh()

    assert dashboard._table.item(0, 0).text() == "Deep Sea Documentary"
    assert dashboard._table.item(0, 1).text() == "facebook"


def test_refresh_shows_readiness_and_progress_for_a_fresh_project(
    qapp: QApplication, tmp_path
) -> None:
    job_store = InMemoryJobStore()
    job_store.add(_job())
    dashboard = _dashboard(tmp_path, job_store)

    dashboard.refresh()

    # A brand-new project (no script, no scenes) is BLOCKED per
    # ProductionReadinessService - the dashboard must show that
    # honestly rather than a fake "in progress" state.
    assert dashboard._table.item(0, 3).text() == "blocked"
    assert dashboard._table.item(0, 4).text() == "10%"


def test_refresh_shows_the_current_actionable_stage_via_project_header_service(
    qapp: QApplication, tmp_path
) -> None:
    """
    The dashboard's stage column must come from the same
    ProjectHeaderService the workspace's own persistent header uses -
    proving the two surfaces can never disagree about what's next.
    """

    job_store = InMemoryJobStore()
    job_store.add(_job())
    dashboard = _dashboard(tmp_path, job_store)

    dashboard.refresh()

    from src.services.project_header_service import ProjectHeaderService

    expected = ProjectHeaderService().summarize(job_store.list_all()[0])
    assert dashboard._table.item(0, 2).text() == expected.current_stage
    assert dashboard._table.item(0, 6).text() == expected.automation_state


def test_empty_job_store_shows_the_empty_state_not_the_table(
    qapp: QApplication, tmp_path
) -> None:
    dashboard = _dashboard(tmp_path, InMemoryJobStore())

    dashboard.refresh()

    # isVisible() reflects the whole ancestor chain, which is never
    # "shown" for a bare widget under test - isHidden() reflects only
    # this widget's own explicit setVisible() call, which is what
    # refresh() actually controls.
    assert dashboard._empty_label.isHidden() is False
    assert dashboard._table.isHidden() is True


def test_double_clicking_a_row_opens_that_project(qapp: QApplication, tmp_path) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    opened: list[object] = []
    dashboard = DashboardView(
        job_store=job_store,
        checkpoint_storage=PipelineCheckpointStorageService(
            storage_root=tmp_path / "checkpoints"
        ),
        on_open_project=opened.append,
    )
    dashboard.refresh()

    dashboard._open_row(0)

    assert opened == [job.id]
