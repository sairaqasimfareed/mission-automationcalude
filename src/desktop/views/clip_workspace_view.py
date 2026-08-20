from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.desktop.job_store import JobStore
from src.desktop.recovery_dialog import show_recoverable_error
from src.desktop.widgets import (
    badge,
    button,
    card,
    muted,
    small_muted,
    status_label,
)
from src.models.bulk_clip_ingestion import BulkClipIngestionEntryStatus
from src.models.bulk_stock_assignment import BulkStockAssignmentEntryStatus
from src.models.video_clip import VideoClip
from src.models.video_job import VideoJob
from src.services.bulk_clip_ingestion_service import BulkClipIngestionService
from src.services.bulk_stock_assignment_service import BulkStockAssignmentService
from src.services.scene_asset_workflow_service import SceneAssetWorkflowService
from src.services.scene_prompt_export_service import ScenePromptExportService

_LEFT = Qt.AlignmentFlag.AlignLeft


class ClipWorkspaceView(QWidget):
    """
    Clip Workspace: per-scene duration and resolved-clip review, plus
    a bulk external-generation workflow.

    Mission Automation plans one visual clip per scene, sized to that
    scene's estimated_duration_seconds - there is no scene-splitting
    backend capability yet (a scene always maps to exactly one
    VideoClip). Most of this workspace is a review surface: each
    scene's planned duration next to its resolved VideoClip (once
    assets are acquired via the Render Workspace) and any workflow
    warnings recorded on the job.

    The one active workflow here is deliberately manual on the
    generation side: this app does not automate any external AI video
    tool's UI (see ScenePromptExportService/BulkClipIngestionService's
    docstrings). It exports every scene's prompt for a human to use in
    whatever tool they choose, then bulk-assigns the downloaded
    results back to their scenes through the same manual-upload
    workflow the Render Workspace already uses one file at a time.
    """

    def __init__(
        self,
        *,
        job_store: JobStore,
        asset_workflow_service: SceneAssetWorkflowService,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__()

        self._job_store = job_store
        self._on_change = on_change
        self._job_id: UUID | None = None
        self._selected_scene_numbers: set[int] = set()

        self._prompt_export_service = ScenePromptExportService()
        self._bulk_ingestion_service = BulkClipIngestionService(
            asset_workflow_service=asset_workflow_service
        )
        self._bulk_stock_assignment_service = BulkStockAssignmentService(
            asset_workflow_service=asset_workflow_service
        )

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        content_container = QWidget()
        self._layout = QVBoxLayout(content_container)
        self._layout.setContentsMargins(0, 12, 4, 0)
        self._layout.setSpacing(16)

        scroll_area.setWidget(content_container)
        outer_layout.addWidget(scroll_area)

    def set_job(self, job_id: UUID) -> None:
        self._job_id = job_id

    def refresh(self, job: VideoJob) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)

            if item is None:
                continue

            widget = item.widget()

            if widget is not None:
                widget.deleteLater()

        self._build_summary_card(job)
        self._build_bulk_generation_card(job)
        self._build_clips_card(job)

    def _build_summary_card(self, job: VideoJob) -> None:
        frame, layout = card("Duration summary", icon_name="clapper")

        total_planned = sum(scene.estimated_duration_seconds for scene in job.scenes)
        total_resolved = sum(clip.duration_seconds for clip in job.video_clips)

        layout.addWidget(
            muted(
                f"{len(job.scenes)} scene(s) planned, "
                f"{total_planned}s total. "
                f"{len(job.video_clips)} clip(s) resolved, "
                f"{total_resolved}s total."
            )
        )

        duration_warnings = [
            warning for warning in job.warnings if "narration" in warning.lower()
        ]

        if duration_warnings:
            layout.addWidget(
                status_label(
                    "Duration warnings:\n"
                    + "\n".join(f"- {warning}" for warning in duration_warnings),
                    role="warning",
                )
            )

        self._layout.addWidget(frame)

    def _build_clips_card(self, job: VideoJob) -> None:
        frame, layout = card(f"Scenes ({len(job.scenes)})", icon_name="clapper")

        if not job.scenes:
            layout.addWidget(small_muted("No scenes planned yet - see Content Studio."))
            self._layout.addWidget(frame)

            return

        valid_scene_numbers = {scene.scene_number for scene in job.scenes}
        self._selected_scene_numbers &= valid_scene_numbers

        layout.addWidget(
            small_muted(
                "Check scenes below, then bulk-assign stock footage to all of "
                "them at once - the top-ranked search result is auto-selected "
                "per scene, the same as picking the first result manually."
            )
        )

        bulk_assign_button = button(
            f"Assign stock footage to {len(self._selected_scene_numbers)} "
            "selected scene(s)",
            variant="primary",
            icon_name="clapper",
        )
        bulk_assign_button.setEnabled(bool(self._selected_scene_numbers))
        bulk_assign_button.clicked.connect(self._handle_bulk_assign_stock)
        layout.addWidget(bulk_assign_button, alignment=_LEFT)

        clips_by_scene = {clip.scene_number: clip for clip in job.video_clips}

        for scene in job.scenes:
            row = QFrame()
            row.setProperty("sceneRow", True)

            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(12, 8, 12, 8)
            row_layout.setSpacing(4)

            select_checkbox = QCheckBox(
                f"#{scene.scene_number} {scene.title} "
                f"({scene.estimated_duration_seconds}s planned)"
            )
            select_checkbox.setChecked(
                scene.scene_number in self._selected_scene_numbers
            )
            select_checkbox.toggled.connect(
                lambda checked, number=scene.scene_number: (
                    self._handle_toggle_scene_selection(number, checked)
                )
            )
            row_layout.addWidget(select_checkbox)
            row_layout.addWidget(small_muted(scene.narration))

            clip = clips_by_scene.get(scene.scene_number)

            if clip is not None:
                row_layout.addLayout(self._clip_summary(clip))
            else:
                row_layout.addWidget(
                    small_muted("No resolved clip yet - see Render Workspace.")
                )

            layout.addWidget(row)

        self._layout.addWidget(frame)

    @staticmethod
    def _clip_summary(clip: VideoClip) -> QVBoxLayout:
        summary_layout = QVBoxLayout()
        summary_layout.setContentsMargins(0, 4, 0, 0)
        summary_layout.setSpacing(2)

        summary_layout.addWidget(
            badge(f"{clip.source_type.value} · {clip.status.value}")
        )
        summary_layout.addWidget(
            small_muted(
                f"{clip.duration_seconds}s"
                f" · {clip.local_file or clip.source_url or 'no file yet'}"
            )
        )

        return summary_layout

    def _build_bulk_generation_card(self, job: VideoJob) -> None:
        frame, layout = card("Bulk external generation", icon_name="clapper")

        layout.addWidget(
            small_muted(
                "Export every scene's prompt, generate the clips yourself in "
                "whatever AI video tool you use, then drop the downloaded "
                "files back in here in one batch. Nothing in this app talks "
                "to that tool directly - you drive the generation, this app "
                "only tracks which file goes with which scene."
            )
        )

        if not job.scenes:
            layout.addWidget(small_muted("No scenes planned yet - see Content Studio."))
            self._layout.addWidget(frame)

            return

        export_button = button(
            "Export prompts...", variant="primary", icon_name="script"
        )
        export_button.clicked.connect(self._handle_export_prompts)
        layout.addWidget(export_button, alignment=_LEFT)

        ingest_button = button(
            "Ingest clips from folder...", variant="primary", icon_name="upload"
        )
        ingest_button.clicked.connect(self._handle_ingest_clips)
        layout.addWidget(ingest_button, alignment=_LEFT)

        self._layout.addWidget(frame)

    def _handle_export_prompts(self) -> None:
        job = self._current_job()

        if job is None:
            return

        destination_path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export scene prompts",
            "scene_prompts.txt",
            "Text files (*.txt)",
        )

        if not destination_path:
            return

        try:
            self._prompt_export_service.write_file(job.scenes, Path(destination_path))
        except OSError as error:
            self._record_error(
                job,
                f"Could not export scene prompts: {error}",
                on_retry=self._handle_export_prompts,
            )

            return

        QMessageBox.information(
            self,
            "Prompts exported",
            f"Exported {len(job.scenes)} scene prompt(s) to:\n{destination_path}",
        )

    def _handle_ingest_clips(self) -> None:
        job = self._current_job()

        if job is None:
            return

        source_directory = QFileDialog.getExistingDirectory(
            self, "Select folder with downloaded clips"
        )

        if not source_directory:
            return

        try:
            result = self._bulk_ingestion_service.ingest(
                job=job, source_directory=Path(source_directory)
            )
        except ValueError as error:
            self._record_error(
                job,
                f"Bulk clip ingestion failed: {error}",
                on_retry=self._handle_ingest_clips,
            )

            return

        summary_lines = [
            f"Assigned: {result.assigned_count}",
            f"Not assigned: {result.failed_count}",
        ]

        if result.scenes_still_missing_a_file:
            missing = ", ".join(str(n) for n in result.scenes_still_missing_a_file)
            summary_lines.append(f"Scenes still missing a file: {missing}")

        problem_entries = [
            f"- {entry.file_name}: {entry.detail}"
            for entry in result.entries
            if entry.status != BulkClipIngestionEntryStatus.ASSIGNED
        ]

        if problem_entries:
            summary_lines.append("")
            summary_lines.append("Issues:")
            summary_lines.extend(problem_entries)

        QMessageBox.information(
            self, "Bulk ingestion complete", "\n".join(summary_lines)
        )
        self._on_change()

    def _handle_toggle_scene_selection(self, scene_number: int, checked: bool) -> None:
        if checked:
            self._selected_scene_numbers.add(scene_number)
        else:
            self._selected_scene_numbers.discard(scene_number)

        job = self._current_job()

        if job is not None:
            self.refresh(job)

    def _handle_bulk_assign_stock(self) -> None:
        job = self._current_job()

        if job is None or not self._selected_scene_numbers:
            return

        scene_numbers = sorted(self._selected_scene_numbers)

        try:
            result = self._bulk_stock_assignment_service.assign(
                job=job, scene_numbers=scene_numbers
            )
        except ValueError as error:
            self._record_error(
                job,
                f"Bulk stock assignment failed: {error}",
                on_retry=self._handle_bulk_assign_stock,
            )

            return

        summary_lines = [
            f"Assigned: {result.assigned_count}",
            f"Not assigned: {result.failed_count}",
        ]

        problem_entries = [
            f"- Scene {entry.scene_number}: {entry.detail}"
            for entry in result.entries
            if entry.status != BulkStockAssignmentEntryStatus.ASSIGNED
        ]

        if problem_entries:
            summary_lines.append("")
            summary_lines.append("Issues:")
            summary_lines.extend(problem_entries)

        QMessageBox.information(
            self, "Bulk stock assignment complete", "\n".join(summary_lines)
        )

        self._selected_scene_numbers.clear()
        self._on_change()

    def _current_job(self) -> VideoJob | None:
        if self._job_id is None:
            return None

        return self._job_store.get(self._job_id)

    def _record_error(
        self,
        job: VideoJob,
        message: str,
        *,
        on_retry: Callable[[], None] | None = None,
    ) -> None:
        job.errors.append(message)
        show_recoverable_error(self, "Step failed", message, on_retry=on_retry)
        self._on_change()
