from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from PySide6.QtCore import QObject, Qt, QThread, Signal
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
    row,
    small_muted,
    status_label,
)
from src.models.bulk_clip_ingestion import BulkClipIngestionEntryStatus
from src.models.bulk_stock_assignment import BulkStockAssignmentEntryStatus
from src.models.google_flow_generation import (
    GoogleFlowGenerationAttempt,
    GoogleFlowGenerationState,
)
from src.models.scene_completeness import SceneCompletenessStatus
from src.models.video_clip import VideoClip
from src.models.video_job import VideoJob
from src.services.bulk_clip_ingestion_service import BulkClipIngestionService
from src.services.bulk_stock_assignment_service import BulkStockAssignmentService
from src.services.scene_asset_workflow_service import SceneAssetWorkflowService
from src.services.scene_completeness_service import SceneCompletenessService
from src.services.scene_prompt_export_service import ScenePromptExportService
from src.services.scene_video_generation_service import SceneVideoGenerationService

_LEFT = Qt.AlignmentFlag.AlignLeft

_COMPLETENESS_STATUS_ROLE = {
    SceneCompletenessStatus.READY: "success",
    SceneCompletenessStatus.IN_PROGRESS: "warning",
    SceneCompletenessStatus.NEEDS_ATTENTION: "error",
    SceneCompletenessStatus.NOT_STARTED: "warning",
}


class _SceneVideoGenerationWorker(QObject):
    """
    Runs one Google Flow scene-generation call (one scene, or every
    planned scene) off the Qt main thread.

    Real Flow generation is a multi-minute, polling-based operation
    (SceneVideoGenerationService.generate_one/generate_all block on
    real waits) - calling it directly from a button handler would
    freeze the whole UI for however long that takes. Mirrors
    _RenderWorker's own established pattern exactly (bound-method
    signal connections, job_id carried as a plain attribute rather
    than a lambda closure) for the same real thread-affinity reason
    documented on that class - a lambda slot has no owning QObject for
    Qt's AutoConnection to detect, and silently runs on the wrong
    thread instead of being queued back to the GUI thread.

    Real-world finding: a multi-scene "Generate All" run genuinely can
    fail or be interrupted partway through (a browser crash on a later
    scene, an unrelated exception, the app closing) - losing every
    already-completed scene's real progress in that case, because
    nothing persisted it until the whole batch finished. scene_completed
    fires after every individual scene (via
    SceneVideoGenerationService.generate_all()'s on_scene_complete
    hook), carrying a deep-copied snapshot rather than the live job
    object - the worker thread keeps mutating the live job for the
    next scene immediately after emitting, so a listener reading the
    live object off the GUI thread could observe a torn, half-mutated
    state; a snapshot taken at a known-consistent instant has no such
    race. The `except Exception` below (not just RuntimeError/ValueError)
    exists for the same reason: a failure type this module hasn't seen
    before should still reach failed.emit() and get a chance to persist,
    not silently kill this thread with no signal at all.
    """

    finished = Signal()
    failed = Signal(str)
    scene_completed = Signal(object)

    def __init__(
        self,
        *,
        service: SceneVideoGenerationService,
        job: VideoJob,
        scene_number: int | None,
        retry_after_auth: bool = False,
    ) -> None:
        super().__init__()

        self._service = service
        self._job = job
        self.job = job
        self.job_id = job.id
        self.scene_number = scene_number
        self._retry_after_auth = retry_after_auth

    def run(self) -> None:
        try:
            if self._retry_after_auth:
                assert self.scene_number is not None  # only ever set together
                self._service.retry_scene_after_auth(self._job, self.scene_number)
            elif self.scene_number is None:
                self._service.generate_all(
                    self._job,
                    on_scene_complete=self._handle_scene_complete,
                )
            else:
                self._service.generate_one(self._job, self.scene_number)
        except Exception as error:  # noqa: BLE001 - reported to the UI thread
            self.failed.emit(str(error))

            return

        self.finished.emit()

    def _handle_scene_complete(self, job: VideoJob, scene_number: int) -> None:
        self.scene_completed.emit(job.model_copy(deep=True))


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
        scene_video_generation_service: SceneVideoGenerationService | None = None,
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

        # Optional: real Google Flow generation requires a configured
        # provider/account (browser profile, provider profile) that
        # not every install has - None disables the automatic
        # generation card entirely rather than failing to construct
        # this view, matching this codebase's established "optional to
        # preserve older call sites" convention.
        self._scene_video_generation_service = scene_video_generation_service
        self._generating_job_ids: set[UUID] = set()
        self._generation_threads: dict[
            UUID, tuple[QThread, _SceneVideoGenerationWorker]
        ] = {}

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
        self._build_automatic_generation_card(job)
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

    def _build_automatic_generation_card(self, job: VideoJob) -> None:
        """
        Real, automatic Google Flow generation: submit -> poll ->
        download -> attach per scene, via SceneVideoGenerationService.

        Separate from the manual export/bulk-ingest workflow below,
        which remains available unchanged - this is an additional,
        faster path for a project with a real Flow account configured,
        not a replacement.
        """

        frame, layout = card(
            "Automatic scene generation (Google Flow)", icon_name="clapper"
        )

        service = self._scene_video_generation_service

        if service is None:
            layout.addWidget(
                small_muted(
                    "No Google Flow provider is configured for this "
                    "installation - use the manual export workflow below."
                )
            )
            self._layout.addWidget(frame)

            return

        if not job.scenes:
            layout.addWidget(small_muted("No scenes planned yet - see Content Studio."))
            self._layout.addWidget(frame)

            return

        is_generating = job.id in self._generating_job_ids

        report = SceneCompletenessService().check(job)
        entries_by_scene = {entry.scene_number: entry for entry in report.entries}

        ready_count = sum(
            1
            for entry in report.entries
            if entry.status == SceneCompletenessStatus.READY
        )
        layout.addWidget(
            muted(f"{ready_count} / {len(report.entries)} scene(s) ready.")
        )

        if is_generating:
            layout.addWidget(
                status_label(
                    "Generating - this can take several minutes per scene.",
                    role="warning",
                )
            )

        all_button = button(
            "Generate all scenes", variant="primary", icon_name="clapper"
        )
        all_button.setEnabled(not is_generating and ready_count < len(report.entries))
        all_button.clicked.connect(self._handle_generate_all_scene_videos)
        layout.addWidget(all_button, alignment=_LEFT)

        for scene in sorted(job.scenes, key=lambda scene: scene.scene_number):
            entry = entries_by_scene.get(scene.scene_number)

            row_layout = QVBoxLayout()
            row_layout.setContentsMargins(0, 4, 0, 4)
            row_layout.setSpacing(2)

            row_layout.addWidget(
                small_muted(f"Scene {scene.scene_number}: {scene.title}")
            )

            if entry is not None:
                row_layout.addWidget(
                    status_label(
                        f"{entry.status.value} - {entry.detail}",
                        role=_COMPLETENESS_STATUS_ROLE[entry.status],
                    )
                )

            stuck_on_auth = self._auth_required_attempt(job, scene.scene_number)

            if stuck_on_auth is not None:
                primary_button = button("Retry after login", variant="primary")
                primary_button.setEnabled(not is_generating)
                primary_button.clicked.connect(
                    lambda checked=False, number=scene.scene_number: (
                        self._handle_retry_scene_after_auth(number)
                    )
                )
            else:
                primary_button = button(
                    "Regenerate"
                    if entry is not None
                    and entry.status == SceneCompletenessStatus.READY
                    else "Generate"
                )
                primary_button.setEnabled(not is_generating)
                primary_button.clicked.connect(
                    lambda checked=False, number=scene.scene_number: (
                        self._handle_generate_scene_video(number)
                    )
                )

            # Real-world finding, 2026-09-26: the only manual-upload
            # path used to be the separate "Bulk external generation"
            # card below (export every prompt, generate elsewhere,
            # re-import a whole folder at once) - awkward for the
            # actual live workflow of generating most scenes
            # automatically and only a few manually (e.g. through a
            # second provider). This button attaches one file to just
            # this scene, right where the decision to generate it
            # automatically is already being made.
            upload_button = button("Upload...", icon_name="upload")
            upload_button.setEnabled(not is_generating)
            upload_button.clicked.connect(
                lambda checked=False, number=scene.scene_number: (
                    self._handle_upload_scene_clip(number)
                )
            )

            row_layout.addLayout(
                row(primary_button, upload_button, stretch_at_end=False)
            )

            layout.addLayout(row_layout)

        self._layout.addWidget(frame)

    @staticmethod
    def _auth_required_attempt(
        job: VideoJob, scene_number: int
    ) -> GoogleFlowGenerationAttempt | None:
        """
        The scene's stuck AUTH_REQUIRED attempt, if any - checked
        across every sub-clip index (a Phase 5 split scene's stuck
        attempt need not be clip_sequence_index=0), not just via
        SceneCompletenessService's own default-index lookup.
        """

        return next(
            (
                attempt
                for attempt in job.flow_generation_attempts
                if attempt.request.scene_number == scene_number
                and attempt.state == GoogleFlowGenerationState.AUTH_REQUIRED
            ),
            None,
        )

    def _handle_generate_scene_video(self, scene_number: int) -> None:
        job = self._current_job()

        if job is None:
            return

        self._execute_scene_generation(job, scene_number=scene_number)

    def _handle_retry_scene_after_auth(self, scene_number: int) -> None:
        job = self._current_job()

        if job is None:
            return

        self._execute_scene_generation(
            job, scene_number=scene_number, retry_after_auth=True
        )

    def _handle_generate_all_scene_videos(self) -> None:
        job = self._current_job()

        if job is None:
            return

        self._execute_scene_generation(job, scene_number=None)

    def _execute_scene_generation(
        self,
        job: VideoJob,
        *,
        scene_number: int | None,
        retry_after_auth: bool = False,
    ) -> None:
        service = self._scene_video_generation_service

        if service is None:
            return

        if job.id in self._generating_job_ids:
            # Already generating for this job - defense in depth, the
            # UI already reflects this via disabled buttons.
            return

        thread = QThread()
        worker = _SceneVideoGenerationWorker(
            service=service,
            job=job,
            scene_number=scene_number,
            retry_after_auth=retry_after_auth,
        )
        worker.moveToThread(thread)

        job_id = job.id
        # QThread is a QObject too, so it can carry job_id for
        # thread.finished below (which has no signal argument to carry
        # it as a parameter) - same convention _RenderWorker/
        # RenderWorkspaceView already establish.
        thread.job_id = job_id  # type: ignore[attr-defined]

        # Bound methods, not lambdas: see _SceneVideoGenerationWorker's
        # own docstring for why - a lambda slot has no owning QObject
        # for Qt's AutoConnection to detect, and silently runs
        # cross-thread instead of being queued back to the GUI thread.
        thread.started.connect(worker.run)
        worker.scene_completed.connect(self._handle_scene_generation_progress)
        worker.finished.connect(self._handle_scene_generation_finished)
        worker.failed.connect(self._handle_scene_generation_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)

        # thread.finished only fires once the underlying OS thread has
        # actually stopped - dropping the (thread, worker) reference
        # any earlier risks garbage-collecting a QThread wrapper while
        # its C++ thread is still shutting down (a real crash, not
        # just a leak), so cleanup is kept separate from and later than
        # the UI-facing "is this job still generating" bookkeeping.
        thread.finished.connect(self._handle_scene_generation_thread_finished)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._generation_threads[job_id] = (thread, worker)
        self._generating_job_ids.add(job_id)

        self._rebuild_card(job)

        thread.start()

    def _handle_scene_generation_progress(self, job: VideoJob) -> None:
        """
        Checkpoint one scene's real progress the moment it completes.

        Persisting here - not just once the whole batch finishes or
        fails - is what actually protects an already-completed
        scene's work against a later scene's failure, an unrelated
        crash, or the app closing mid-batch. Deliberately unconditional
        on which job is currently selected: only the UI refresh below
        depends on that, persistence must not.
        """

        self._job_store.add(job)

        if job.id == self._job_id:
            self._on_change()

    def _handle_scene_generation_finished(self) -> None:
        worker = self.sender()

        if not isinstance(worker, _SceneVideoGenerationWorker):
            return

        job_id = worker.job_id
        self._generating_job_ids.discard(job_id)

        # Unconditional for the same reason as
        # _handle_scene_generation_progress - the worker's job holds
        # this run's real final state regardless of which job the
        # user happens to be looking at right now.
        self._job_store.add(worker.job)

        if job_id == self._job_id:
            self._on_change()

    def _handle_scene_generation_failed(self, message: str) -> None:
        worker = self.sender()

        if not isinstance(worker, _SceneVideoGenerationWorker):
            return

        job_id = worker.job_id
        scene_number = worker.scene_number
        self._generating_job_ids.discard(job_id)

        job = worker.job
        job.errors.append(f"Scene video generation failed: {message}")

        # Unconditional: this persists every scene the worker actually
        # completed before the failure, not just when the failed job
        # happens to still be the one on screen - see
        # _handle_scene_generation_progress.
        self._job_store.add(job)

        if job_id == self._job_id:

            def on_retry() -> None:
                self._execute_scene_generation(job, scene_number=scene_number)

            show_recoverable_error(
                self, "Scene generation failed", message, on_retry=on_retry
            )
            self._on_change()

    def _handle_scene_generation_thread_finished(self) -> None:
        """Drop the (thread, worker) bookkeeping entry once the QThread has stopped."""

        thread = self.sender()
        job_id = getattr(thread, "job_id", None)

        if job_id is not None:
            self._generation_threads.pop(job_id, None)

    def _rebuild_card(self, job: VideoJob) -> None:
        if job.id == self._job_id:
            self.refresh(job)

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
            self._prompt_export_service.write_file(
                job.scenes,
                Path(destination_path),
                cinematic_prompt_package=job.cinematic_prompt_package,
            )
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

    def _handle_upload_scene_clip(self, scene_number: int) -> None:
        job = self._current_job()

        if job is None:
            return

        file_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            f"Upload clip for scene {scene_number}",
            "",
            "Video files (*.mp4 *.mov *.mkv *.webm *.avi *.m4v)",
        )

        if not file_path:
            return

        entry = self._bulk_ingestion_service.ingest_one(
            job=job, scene_number=scene_number, file_path=Path(file_path)
        )

        if entry.status != BulkClipIngestionEntryStatus.ASSIGNED:
            self._record_error(
                job,
                f"Could not attach clip to scene {scene_number}: {entry.detail}",
                on_retry=lambda: self._handle_upload_scene_clip(scene_number),
            )

            return

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
