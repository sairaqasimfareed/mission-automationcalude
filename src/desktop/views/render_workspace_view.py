from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QLineEdit,
    QProgressBar,
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
    subheading,
)
from src.models.asset_state import SceneAssetState
from src.models.render_orchestration_result import RenderOrchestrationResult
from src.models.render_progress import RenderProgress
from src.models.scene import Scene
from src.models.video_job import VideoJob
from src.services.policy_service import PolicyService
from src.services.project_render_runtime_factory import ProjectRenderRuntimeFactory
from src.services.render_orchestrator_service import RenderOrchestratorService
from src.services.scene_asset_workflow_service import SceneAssetWorkflowService

_LEFT = Qt.AlignmentFlag.AlignLeft


class _RenderWorker(QObject):
    """
    Runs one render orchestration call off the Qt main thread.

    progress/finished/failed are ordinary Qt signals - Qt's
    AutoConnection resolves queued-vs-direct delivery by comparing the
    calling thread to the receiving slot's owning thread at emit()
    time, not the emitting QObject's own thread affinity, so cross-
    thread delivery is safe even though FFmpegExecutionService actually
    invokes progress_callback from its own separate daemon thread (a
    third thread beyond this worker's thread and the Qt main thread).
    """

    progress = Signal(object)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        *,
        orchestrator: RenderOrchestratorService,
        job: VideoJob,
        user_input: dict[str, object] | None,
    ) -> None:
        super().__init__()

        self._orchestrator = orchestrator
        self._job = job
        self._user_input = user_input

    def run(self) -> None:
        try:
            result = self._orchestrator.execute(
                self._job,
                dry_run=True,
                user_input=self._user_input,
                progress_callback=self.progress.emit,
            )
        except Exception as error:  # noqa: BLE001 - reported to the UI thread
            self.failed.emit(str(error))

            return

        self.finished.emit(result)


class RenderWorkspaceView(QWidget):
    """
    Render Workspace: per-scene visual asset resolution and FFmpeg
    render execution.

    Render runs in dry-run mode. When a scene has no local asset
    match, the asset stage pauses (WAITING_FOR_USER) rather than
    failing outright, and this workspace lets the user resolve each
    scene either by choosing a local file to upload, or by searching
    stock footage and selecting a result. Stock search runs
    immediately in-process (SceneAssetWorkflowService.search_stock(),
    mutating the same SceneAssetState objects already stored on the
    VideoJob from the paused render) - it does not need a render round
    trip. Submitting the final per-scene decisions re-runs render on
    the same VideoJob with them attached as user_input; selecting a
    stock candidate acquires it (downloads and stores it locally)
    within that same call.
    """

    def __init__(
        self,
        *,
        job_store: JobStore,
        render_runtime_factory: ProjectRenderRuntimeFactory,
        asset_workflow_service: SceneAssetWorkflowService,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__()

        self._job_store = job_store
        self._render_runtime_factory = render_runtime_factory
        self._asset_workflow_service = asset_workflow_service
        self._on_change = on_change
        self._job_id: UUID | None = None
        self._manual_upload_paths: dict[int, str] = {}
        self._selected_stock_candidate_index: dict[int, int] = {}
        self._policy_service = PolicyService()
        self._render_threads: dict[UUID, tuple[QThread, _RenderWorker]] = {}
        self._rendering_job_ids: set[UUID] = set()

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
        self._manual_upload_paths = {}
        self._selected_stock_candidate_index = {}

    def refresh(self, job: VideoJob) -> None:
        if job.id in self._rendering_job_ids:
            # A render for this job is in flight - its progress widgets
            # are being updated live by the signal handlers below, not
            # through refresh(). refresh() can be triggered by an
            # unrelated workspace's on_change (every workspace shares
            # the same on_change callback), so rebuilding here would
            # destroy the live widgets mid-render even though this
            # workspace isn't the one that changed.
            return

        self._rebuild_card(job)

    def _rebuild_card(self, job: VideoJob) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)

            if item is None:
                continue

            widget = item.widget()

            if widget is not None:
                widget.deleteLater()

        self._build_render_card(job)

    def _build_render_card(self, job: VideoJob) -> None:
        frame, layout = card("Render", icon_name="play")

        assert self._job_id is not None

        if job.id in self._rendering_job_ids:
            self._build_render_progress_state(layout)
            self._layout.addWidget(frame)

            return

        waiting_scene_numbers = [
            state.scene_number
            for state in job.scene_asset_states
            if state.requires_user_decision
        ]

        render_result = self._job_store.get_render_result(self._job_id)

        if waiting_scene_numbers:
            layout.addWidget(
                muted(
                    "These scenes need a visual asset before render can "
                    "continue. For each one, either choose a local file to "
                    "upload, or search stock footage and select a result."
                )
            )

            for scene_number in waiting_scene_numbers:
                self._build_scene_asset_choice(
                    layout,
                    job=job,
                    scene_number=scene_number,
                )

            submit_button = button(
                "Submit choices and continue render",
                variant="primary",
                icon_name="play",
            )
            submit_button.clicked.connect(self._handle_submit_asset_decisions)
            layout.addWidget(submit_button, alignment=_LEFT)
        elif render_result is not None:
            layout.addWidget(
                status_label("Render succeeded.", role="success")
                if render_result.success
                else status_label("Render failed.", role="error")
            )
            layout.addWidget(badge(render_result.status.value))

            if render_result.render_result is not None:
                layout.addWidget(
                    small_muted(
                        f"Output file: {render_result.render_result.output_file}"
                    ),
                )

            if render_result.errors:
                layout.addWidget(
                    status_label(
                        "Errors:\n"
                        + "\n".join(f"- {error}" for error in render_result.errors),
                        role="error",
                    )
                )

            if render_result.warnings:
                layout.addWidget(
                    status_label(
                        "Warnings:\n"
                        + "\n".join(
                            f"- {warning}" for warning in render_result.warnings
                        ),
                        role="warning",
                    )
                )

            retry_button = button("Run render again", variant="ghost", icon_name="play")
            retry_button.clicked.connect(self._handle_run_render)
            layout.addWidget(retry_button, alignment=_LEFT)
        elif job.scenes:
            layout.addWidget(small_muted("Not rendered yet."))

            render_button = button("Run render", variant="primary", icon_name="play")
            render_button.clicked.connect(self._handle_run_render)
            layout.addWidget(render_button, alignment=_LEFT)
        else:
            layout.addWidget(small_muted("Requires planned scenes."))

        self._layout.addWidget(frame)

    def _build_render_progress_state(self, layout: QVBoxLayout) -> None:
        layout.addWidget(subheading("Rendering..."))

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        layout.addWidget(self._progress_bar)

        self._progress_time_label = small_muted("0.0s")
        layout.addWidget(self._progress_time_label)

        self._progress_speed_label = small_muted("Speed: —")
        layout.addWidget(self._progress_speed_label)

        render_button = button("Run render", variant="primary", icon_name="play")
        render_button.setEnabled(False)
        layout.addWidget(render_button, alignment=_LEFT)

    def _build_scene_asset_choice(
        self,
        layout: QVBoxLayout,
        *,
        job: VideoJob,
        scene_number: int,
    ) -> None:
        frame = QFrame()
        frame.setProperty("sceneRow", True)

        inner_layout = QVBoxLayout(frame)
        inner_layout.setContentsMargins(12, 12, 12, 12)
        inner_layout.setSpacing(8)

        inner_layout.addWidget(subheading(f"Scene {scene_number}"))

        state = self._scene_asset_state(job, scene_number)
        stock_index = self._selected_stock_candidate_index.get(scene_number)
        manual_path = self._manual_upload_paths.get(scene_number)

        if (
            stock_index is not None
            and state is not None
            and 0 <= stock_index < len(state.stock_candidates)
        ):
            candidate = state.stock_candidates[stock_index]
            inner_layout.addWidget(
                status_label(
                    f"Selected stock result: {candidate.title} "
                    f"({candidate.provider})",
                    role="success",
                )
            )
        elif manual_path is not None:
            inner_layout.addWidget(
                status_label(f"Manual upload: {manual_path}", role="success")
            )
        else:
            inner_layout.addWidget(small_muted("No choice made yet."))

        choose_button = button("Choose file for manual upload", icon_name="upload")
        choose_button.clicked.connect(
            lambda checked=False, n=scene_number: (
                self._handle_choose_manual_upload(n)
            ),
        )
        inner_layout.addWidget(choose_button, alignment=_LEFT)

        query_input = QLineEdit()
        query_input.setPlaceholderText("Stock search query (optional)")

        if state is not None and state.stock_search_query:
            query_input.setPlaceholderText(state.stock_search_query)

        inner_layout.addWidget(query_input)

        search_button = button("Search stock footage", icon_name="search")
        search_button.clicked.connect(
            lambda checked=False, n=scene_number, q=query_input: (
                self._handle_search_stock(n, q.text())
            ),
        )
        inner_layout.addWidget(search_button, alignment=_LEFT)

        if state is not None and state.stock_candidates:
            for index, candidate in enumerate(state.stock_candidates):
                candidate_row = QFrame()
                candidate_layout = QVBoxLayout(candidate_row)
                candidate_layout.setContentsMargins(0, 4, 0, 4)
                candidate_layout.setSpacing(4)

                candidate_layout.addWidget(
                    small_muted(
                        f"{index + 1}. {candidate.title} - "
                        f"{candidate.provider or 'Unknown provider'} "
                        f"({candidate.license_type or 'unknown license'})"
                    )
                )

                select_button = button(
                    f"Select result {index + 1}",
                    variant="ghost",
                    icon_name="check",
                )
                select_button.clicked.connect(
                    lambda checked=False, n=scene_number, i=index: (
                        self._handle_select_stock_candidate(n, i)
                    ),
                )
                candidate_layout.addWidget(select_button, alignment=_LEFT)

                inner_layout.addWidget(candidate_row)

        layout.addWidget(frame)

    def _handle_run_render(self) -> None:
        job = self._current_job()

        if job is None or not job.scenes:
            return

        self._execute_render(job)

    def _handle_choose_manual_upload(self, scene_number: int) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            f"Select video file for scene {scene_number}",
            "",
            "Video files (*.mp4 *.mov *.mkv *.webm *.avi *.m4v)",
        )

        if not file_path:
            return

        self._manual_upload_paths[scene_number] = file_path
        self._selected_stock_candidate_index.pop(scene_number, None)
        self._on_change()

    def _handle_search_stock(self, scene_number: int, query_text: str) -> None:
        job = self._current_job()

        if job is None:
            return

        scene = self._scene_by_number(job, scene_number)
        state = self._scene_asset_state(job, scene_number)

        if scene is None or state is None:
            return

        cleaned_query = query_text.strip()

        if cleaned_query:
            scene.stock_query = cleaned_query

        try:
            self._asset_workflow_service.search_stock(scene=scene, state=state)
        except (RuntimeError, ValueError) as error:
            self._record_error(
                job,
                f"Stock search failed: {error}",
                on_retry=lambda: self._handle_search_stock(scene_number, query_text),
            )

            return

        self._on_change()

    def _handle_select_stock_candidate(
        self,
        scene_number: int,
        candidate_index: int,
    ) -> None:
        self._selected_stock_candidate_index[scene_number] = candidate_index
        self._manual_upload_paths.pop(scene_number, None)
        self._on_change()

    def _handle_submit_asset_decisions(self) -> None:
        job = self._current_job()

        if job is None:
            return

        waiting_scene_numbers = [
            state.scene_number
            for state in job.scene_asset_states
            if state.requires_user_decision
        ]

        missing_scene_numbers = [
            scene_number
            for scene_number in waiting_scene_numbers
            if scene_number not in self._manual_upload_paths
            and scene_number not in self._selected_stock_candidate_index
        ]

        if missing_scene_numbers:
            self._record_error(
                job,
                "Choose a file or select stock footage for every scene "
                "before submitting: "
                + ", ".join(str(number) for number in missing_scene_numbers),
            )

            return

        asset_decisions: list[dict[str, object]] = []

        for scene_number in waiting_scene_numbers:
            if scene_number in self._selected_stock_candidate_index:
                asset_decisions.append(
                    {
                        "scene_number": scene_number,
                        "decision": "use_stock",
                        "selected_candidate_index": (
                            self._selected_stock_candidate_index[scene_number]
                        ),
                        "project_id": job.project_name,
                    }
                )
            else:
                asset_decisions.append(
                    {
                        "scene_number": scene_number,
                        "decision": "manual_upload",
                        "manual_upload_path": (self._manual_upload_paths[scene_number]),
                        "project_id": job.project_name,
                    }
                )

        self._execute_render(job, user_input={"asset_decisions": asset_decisions})

    def _execute_render(
        self,
        job: VideoJob,
        *,
        user_input: dict[str, object] | None = None,
    ) -> None:
        if job.id in self._rendering_job_ids:
            # Already rendering this job - the UI already reflects this
            # (disabled button), this is just defense in depth.
            return

        try:
            render_orchestrator = self._render_runtime_factory.build(
                job=job,
                genre_id=job.genre_id,
                overrides_by_scene=job.scene_editing_overrides or None,
            )
        except (RuntimeError, ValueError) as error:
            self._record_error(
                job,
                f"Render setup failed: {error}",
                on_retry=lambda: self._execute_render(job, user_input=user_input),
            )

            return

        thread = QThread()
        worker = _RenderWorker(
            orchestrator=render_orchestrator,
            job=job,
            user_input=user_input,
        )
        worker.moveToThread(thread)

        job_id = job.id

        thread.started.connect(worker.run)
        worker.progress.connect(
            lambda progress, jid=job_id: self._handle_render_progress(jid, progress)
        )
        worker.finished.connect(
            lambda result, jid=job_id: self._handle_render_finished(jid, result)
        )
        worker.failed.connect(
            lambda message, jid=job_id, ui=user_input: self._handle_render_failed(
                jid, message, ui
            )
        )
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)

        # thread.finished only fires once the underlying OS thread has
        # actually stopped (thread.quit() just requests that - it takes
        # another event-loop turn). Dropping our reference to thread/
        # worker any earlier than that (for example in the worker's own
        # finished/failed handlers below) risks Python garbage-collecting
        # a QThread wrapper while its C++ thread is still shutting down,
        # which is a real crash, not just a leak - so thread-lifetime
        # cleanup is intentionally kept separate from, and later than,
        # the UI-facing "is this job still rendering" bookkeeping.
        thread.finished.connect(lambda jid=job_id: self._render_threads.pop(jid, None))
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._render_threads[job_id] = (thread, worker)
        self._rendering_job_ids.add(job_id)

        # Show the in-progress state immediately - nothing else will
        # refresh this workspace until the render finishes.
        self._rebuild_card(job)

        thread.start()

    def _handle_render_progress(self, job_id: UUID, progress: RenderProgress) -> None:
        if job_id != self._job_id:
            return

        self._progress_bar.setValue(int(progress.progress_percent))

        if progress.total_duration_seconds is not None:
            self._progress_time_label.setText(
                f"{progress.processed_duration_seconds:.1f}s / "
                f"{progress.total_duration_seconds:.1f}s"
            )
        else:
            self._progress_time_label.setText(
                f"{progress.processed_duration_seconds:.1f}s"
            )

        self._progress_speed_label.setText(
            f"Speed: {progress.speed:.2f}x"
            if progress.speed is not None
            else "Speed: —"
        )

    def _handle_render_finished(
        self,
        job_id: UUID,
        result: RenderOrchestrationResult,
    ) -> None:
        self._rendering_job_ids.discard(job_id)

        if result.success:
            # Run the quality/policy check automatically as soon as
            # there's a completed render to evaluate, rather than
            # requiring a separate manual click in Quality Center - it
            # can still be re-run manually there after later changes
            # (e.g. a new SEO package or thumbnail).
            self._policy_service.evaluate(result.job)

        self._job_store.set_render_result(job_id, result)

        if job_id == self._job_id:
            self._on_change()

    def _handle_render_failed(
        self,
        job_id: UUID,
        message: str,
        user_input: dict[str, object] | None = None,
    ) -> None:
        self._rendering_job_ids.discard(job_id)

        job = self._job_store.get(job_id)

        if job is not None:
            job.errors.append(f"Render failed: {message}")

        if job_id == self._job_id:
            on_retry = (
                (lambda: self._execute_render(job, user_input=user_input))
                if job is not None
                else None
            )
            show_recoverable_error(self, "Render failed", message, on_retry=on_retry)
            self._on_change()

    def _current_job(self) -> VideoJob | None:
        if self._job_id is None:
            return None

        return self._job_store.get(self._job_id)

    @staticmethod
    def _scene_by_number(job: VideoJob, scene_number: int) -> Scene | None:
        for scene in job.scenes:
            if scene.scene_number == scene_number:
                return scene

        return None

    @staticmethod
    def _scene_asset_state(
        job: VideoJob,
        scene_number: int,
    ) -> SceneAssetState | None:
        for state in job.scene_asset_states:
            if state.scene_number == scene_number:
                return state

        return None

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
