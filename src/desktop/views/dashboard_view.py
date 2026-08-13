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


class DashboardView(QWidget):
    """
    Project dashboard.

    Shows every project known to the injected JobStore, plus a count
    of job IDs with at least one persisted render checkpoint (from
    PipelineCheckpointStorageService, a separate store scoped to the
    render stage only).
    """

    def __init__(
        self,
        *,
        job_store: JobStore,
        checkpoint_storage: PipelineCheckpointStorageService,
        on_open_project: Callable[[UUID], None],
    ) -> None:
        super().__init__()

        self._job_store = job_store
        self._checkpoint_storage = checkpoint_storage
        self._on_open_project = on_open_project
        self._job_ids: list[UUID] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        layout.addWidget(heading("Projects"))

        self._empty_label = muted("No projects yet. Use New Project to create one.")
        layout.addWidget(self._empty_label)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Project", "Topic", "Stage", "Status"])
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.itemDoubleClicked.connect(self._handle_row_activated)
        layout.addWidget(self._table)

        open_button = button("Open selected", variant="primary", icon_name="folder")
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
            self._table.setItem(row_index, 0, QTableWidgetItem(job.project_name))
            self._table.setItem(row_index, 1, QTableWidgetItem(job.topic))
            self._table.setItem(row_index, 2, QTableWidgetItem(job.current_stage.value))
            self._table.setItem(row_index, 3, QTableWidgetItem(job.status.value))

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
