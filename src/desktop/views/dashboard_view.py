from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.desktop.job_store import JobStore
from src.desktop.widgets import button, heading, muted, row, small_muted
from src.services.pipeline_checkpoint_storage_service import (
    PipelineCheckpointStorageService,
)
from src.services.project_header_service import ProjectHeaderService

# Coarse, honest progress proxy (Content Studio Redesign, Phase 3) -
# not a precise percentage of work done, just an ordered position
# among the 4 states ProductionReadinessService already reports.
# Never invents finer granularity than that service actually knows.
_READINESS_PROGRESS_PERCENT = {
    "blocked": 10,
    "ready for render": 55,
    "ready for final export": 80,
    "completed": 100,
}


class DashboardView(QWidget):
    """
    Project dashboard.

    Shows every project known to the injected JobStore, plus a count
    of job IDs with at least one persisted render checkpoint (from
    PipelineCheckpointStorageService, a separate store scoped to the
    render stage only).

    Current-stage/readiness/progress columns are computed via
    ProjectHeaderService - the same service ProjectWorkspaceView's
    persistent header already uses - so the dashboard's "what's next"
    answer can never drift from what a user sees once they open the
    project (Content Studio Redesign, Phase 3: "a user can always tell
    what is done, what is next, and why a stage is blocked").
    """

    def __init__(
        self,
        *,
        job_store: JobStore,
        checkpoint_storage: PipelineCheckpointStorageService,
        project_header_service: ProjectHeaderService | None = None,
        on_open_project: Callable[[UUID], None],
    ) -> None:
        super().__init__()

        self._job_store = job_store
        self._checkpoint_storage = checkpoint_storage
        self._project_header_service = project_header_service or ProjectHeaderService()
        self._on_open_project = on_open_project
        self._job_ids: list[UUID] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        layout.addWidget(heading("Projects"))

        self._empty_label = muted("No projects yet. Use New Project to create one.")
        layout.addWidget(self._empty_label)

        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels(
            [
                "Project",
                "Platform",
                "Current stage",
                "Readiness",
                "Progress",
                "Last modified",
                "Automation",
            ]
        )
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.itemDoubleClicked.connect(self._handle_row_activated)
        layout.addWidget(self._table)

        open_button = button(
            "Continue Production", variant="primary", icon_name="folder"
        )
        open_button.clicked.connect(self._handle_open_clicked)
        layout.addLayout(row(open_button))

        self._checkpoint_label = small_muted("")
        layout.addWidget(self._checkpoint_label)

    def refresh(self) -> None:
        """Reload the dashboard from the job store and checkpoint storage."""

        jobs = self._job_store.list_all()
        self._job_ids = [job.id for job in jobs]

        self._empty_label.setVisible(not jobs)
        self._table.setVisible(bool(jobs))

        self._table.setRowCount(len(jobs))

        for row_index, job in enumerate(jobs):
            summary = self._project_header_service.summarize(job)
            progress_percent = _READINESS_PROGRESS_PERCENT.get(
                summary.readiness_state, 0
            )

            self._table.setItem(row_index, 0, QTableWidgetItem(job.project_name))
            self._table.setItem(row_index, 1, QTableWidgetItem(job.platform.value))
            self._table.setItem(row_index, 2, QTableWidgetItem(summary.current_stage))
            self._table.setItem(row_index, 3, QTableWidgetItem(summary.readiness_state))
            self._table.setItem(row_index, 4, QTableWidgetItem(f"{progress_percent}%"))
            self._table.setItem(
                row_index,
                5,
                QTableWidgetItem(job.updated_at.strftime("%Y-%m-%d %H:%M")),
            )
            self._table.setItem(
                row_index, 6, QTableWidgetItem(summary.automation_state)
            )

        checkpointed_count = len(self._checkpoint_storage.list_job_ids())

        self._checkpoint_label.setText(
            f"{checkpointed_count} job(s) with a persisted render checkpoint."
        )

    def _handle_row_activated(self, item: QTableWidgetItem) -> None:
        self._open_row(item.row())

    def _handle_open_clicked(self) -> None:
        selected = self._table.selectionModel().selectedRows()

        if selected:
            self._open_row(selected[0].row())

    def _open_row(self, row_index: int) -> None:
        if 0 <= row_index < len(self._job_ids):
            self._on_open_project(self._job_ids[row_index])
