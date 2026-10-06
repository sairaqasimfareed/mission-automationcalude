from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.desktop.job_store import JobStore
from src.desktop.recovery_dialog import show_recoverable_error
from src.desktop.widgets import (
    ExpandableList,
    badge,
    button,
    card,
    muted,
    row,
    small_muted,
    status_label,
    subheading,
)
from src.models.bulk_clip_ingestion import BulkClipIngestionEntryStatus
from src.models.bulk_stock_assignment import BulkStockAssignmentEntryStatus
from src.models.clip_attachment_verification import (
    ClipAttachmentVerificationReport,
    ClipVerificationIssueCode,
    ClipVerificationSeverity,
    ReferenceUse,
    SceneClipVerification,
    SceneReferenceStatus,
)
from src.models.google_flow_generation import (
    GoogleFlowGenerationAttempt,
    GoogleFlowGenerationState,
    is_terminal_state,
)
from src.models.muse_generation import MuseGenerationAttempt, MuseGenerationState
from src.models.muse_generation import is_terminal_state as muse_is_terminal_state
from src.models.provider_profile import ProviderCategory
from src.models.scene import Scene
from src.models.scene_completeness import SceneCompletenessStatus
from src.models.video_clip import VideoClip
from src.models.video_job import VideoJob
from src.models.video_provider import VideoProvider
from src.services.bulk_clip_ingestion_service import BulkClipIngestionService
from src.services.bulk_stock_assignment_service import BulkStockAssignmentService
from src.services.clip_attachment_verification_service import (
    ClipAttachmentVerificationService,
    clip_signature,
)
from src.services.google_flow_generation_orchestrator_service import (
    GoogleFlowAttemptCreditSensitiveError,
)
from src.services.muse_generation_orchestrator_service import (
    MuseAttemptCreditSensitiveError,
)
from src.services.reference_frame_selection_service import (
    ReferenceFrameSelectionService,
)
from src.services.reference_refresh_service import (
    ReferenceRefreshReport,
    ReferenceRefreshService,
)
from src.services.registry.provider_registry import ProviderRegistry
from src.services.scene_asset_workflow_service import SceneAssetWorkflowService
from src.services.scene_completeness_service import SceneCompletenessService
from src.services.scene_generation_dispatch_service import (
    SceneGenerationDispatchService,
)
from src.services.scene_prompt_export_service import ScenePromptExportService
from src.services.video_provider_rules import (
    muse_target_seconds,
    resolve_scene_video_provider,
    rules_for,
)
from src.shared.logger import logger

_LEFT = Qt.AlignmentFlag.AlignLeft

# How many rows each long list shows before "Show all" (a 100-scene project
# would otherwise be a very long scroll).
_CLIP_CHECK_PROBLEM_ROWS_VISIBLE = 10
_CLIP_CHECK_OK_ROWS_VISIBLE = 3
_SCENE_ROWS_VISIBLE = 15

# Reference problems are shown on the reference's own line (with its picture),
# so their issue messages are not repeated below it.
_REFERENCE_ISSUE_CODES = frozenset(
    {
        ClipVerificationIssueCode.CHARACTER_WITHOUT_REFERENCE,
        ClipVerificationIssueCode.REFERENCE_NOT_ATTACHED,
    }
)

_COMPLETENESS_STATUS_ROLE = {
    SceneCompletenessStatus.READY: "success",
    SceneCompletenessStatus.IN_PROGRESS: "warning",
    SceneCompletenessStatus.NEEDS_ATTENTION: "error",
    SceneCompletenessStatus.NOT_STARTED: "warning",
}


def _sub_clip_status_role(status_text: str) -> str:
    """
    Same color convention as _COMPLETENESS_STATUS_ROLE, applied to
    SceneCompletenessService.sub_clip_statuses' own plain-text labels
    (not a SceneCompletenessStatus enum, since a sub-clip's own state
    is a raw provider state string, not a full completeness judgment -
    see that method's own docstring for why).
    """

    if status_text.startswith("needs_attention"):
        return "error"

    if status_text == "ready":
        return "success"

    return "warning"


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
        service: SceneGenerationDispatchService,
        job: VideoJob,
        scene_number: int | None,
        retry_after_auth: bool = False,
        forced_profile_id: str | None = None,
        verifier: ClipAttachmentVerificationService | None = None,
    ) -> None:
        super().__init__()

        self._service = service
        self._verifier = verifier
        self._job = job
        self.job = job
        self.job_id = job.id
        self.scene_number = scene_number
        self._retry_after_auth = retry_after_auth
        self._forced_profile_id = forced_profile_id

    def run(self) -> None:
        try:
            if self._retry_after_auth:
                assert self.scene_number is not None  # only ever set together
                self._service.retry_scene_after_auth(self._job, self.scene_number)
            elif self.scene_number is None:
                self._service.generate_all(
                    self._job,
                    forced_profile_id=self._forced_profile_id,
                    on_scene_complete=self._handle_scene_complete,
                )
            else:
                self._service.generate_one(self._job, self.scene_number)
        except Exception as error:  # noqa: BLE001 - reported to the UI thread
            self._verify_quietly()
            self.failed.emit(str(error))

            return

        self._verify_quietly()
        self.finished.emit()

    def _verify_quietly(self) -> None:
        """
        After a whole-project run, check that every scene really ended up
        with its own clip, so a run left unattended has its verdict waiting.
        Runs on this worker thread (it probes and thumbnails every clip) and
        can never fail the run itself - a check that cannot run is just
        absent, and the Check clips button is still there.
        """

        if self._verifier is None or self.scene_number is not None:
            return

        try:
            self._job.clip_verification_report = self._verifier.verify(self._job)
        except Exception:  # noqa: BLE001
            logger.exception("Post-generation clip check failed.")

    def _handle_scene_complete(self, job: VideoJob, scene_number: int) -> None:
        self.scene_completed.emit(job.model_copy(deep=True))


class _ClipVerificationWorker(QObject):
    """Runs one clip check off the Qt main thread (it runs ffprobe and
    ffmpeg once per clip). Same bound-method signal convention as
    _SceneVideoGenerationWorker; verifies a snapshot, so the GUI thread never
    shares the job with this one."""

    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self, *, verifier: ClipAttachmentVerificationService, job: VideoJob
    ) -> None:
        super().__init__()

        self._verifier = verifier
        self._job = job
        self.job_id = job.id

    def run(self) -> None:
        try:
            report = self._verifier.verify(self._job)
        except Exception as error:  # noqa: BLE001 - reported to the UI thread
            self.failed.emit(str(error))

            return

        self.finished.emit(report)


class _ReferenceRefreshWorker(QObject):
    """Re-picks the references off the Qt main thread (it decodes and scores frames
    of every generated clip). Works on a deep copy; the result is brought back onto
    the real job on the GUI thread with ReferenceRefreshService.apply_to."""

    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, *, service: ReferenceRefreshService, job: VideoJob) -> None:
        super().__init__()

        self._service = service
        self._job = job
        self.job_id = job.id

    def run(self) -> None:
        try:
            report = self._service.refresh(self._job)
        except Exception as error:  # noqa: BLE001 - reported to the UI thread
            self.failed.emit(str(error))

            return

        self.finished.emit((self._job, report))


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
        scene_video_generation_service: SceneGenerationDispatchService | None = None,
        provider_registry: ProviderRegistry | None = None,
        clip_verification_service: ClipAttachmentVerificationService | None = None,
        reference_refresh_service: ReferenceRefreshService | None = None,
    ) -> None:
        super().__init__()

        self._job_store = job_store
        self._clip_verification_service = (
            clip_verification_service
            or ClipAttachmentVerificationService(
                thumbnails_root=Path("data/clip_thumbnails")
            )
        )
        self._reference_refresh_service = (
            reference_refresh_service
            or ReferenceRefreshService(
                selection_service=ReferenceFrameSelectionService(),
                storage_root=Path("data/extracted_frames"),
            )
        )
        self._refreshing_job_ids: set[UUID] = set()
        self._refresh_threads: dict[UUID, tuple[QThread, _ReferenceRefreshWorker]] = {}
        # What the last refresh did, shown under the buttons. Feedback about an
        # action, not a fact about the video, so it lives with the view.
        self._refresh_notices: dict[UUID, tuple[str, str]] = {}
        self._verifying_job_ids: set[UUID] = set()
        self._verification_threads: dict[
            UUID, tuple[QThread, _ClipVerificationWorker]
        ] = {}
        self._on_change = on_change
        self._job_id: UUID | None = None
        self._selected_scene_numbers: set[int] = set()
        self._provider_registry = provider_registry
        # Holds the "Generate all scenes" account dropdown's current
        # combo box - rebuilt on every refresh() (matching this
        # view's own "no widgets survive a refresh" convention), so
        # _handle_generate_all_scene_videos() reads whatever the
        # operator currently has selected.
        self._generate_all_account_combo: QComboBox | None = None

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
        self._build_verification_card(job)
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

    def _build_verification_card(self, job: VideoJob) -> None:
        """
        "Did every scene get the right clip?" - one verdict, then a still from
        each scene's clip beside its narration so the picture can be checked
        by eye. Filled in automatically at the end of Generate all scenes;
        Check clips re-runs it any time (after a manual swap, say).
        """

        frame, layout = card("Clip check", icon_name="clapper")

        if not job.scenes:
            layout.addWidget(small_muted("No scenes planned yet - see Content Studio."))
            self._layout.addWidget(frame)

            return

        checking = job.id in self._verifying_job_ids
        check_button = button(
            "Checking clips..." if checking else "Check clips now",
            variant="primary",
            icon_name="clapper",
        )
        check_button.setEnabled(not checking and job.id not in self._generating_job_ids)
        check_button.clicked.connect(self._handle_check_clips)

        bible = job.visual_continuity_bible
        has_identities = bible is not None and bool(bible.identities)
        refreshing = job.id in self._refreshing_job_ids
        refresh_button = button(
            "Refreshing references..." if refreshing else "Refresh references",
            icon_name="clapper",
        )
        refresh_button.setToolTip(
            "Re-pick each character's and place's reference picture from the "
            "clips generated so far, replacing one only when the new frame is "
            "clearly better. Existing clips are not changed."
        )
        refresh_button.setEnabled(
            has_identities
            and not refreshing
            and not checking
            and job.id not in self._generating_job_ids
        )
        refresh_button.setVisible(has_identities)
        refresh_button.clicked.connect(self._handle_refresh_references)
        layout.addLayout(row(check_button, refresh_button))

        notice = self._refresh_notices.get(job.id)

        if notice is not None:
            layout.addWidget(status_label(notice[0], role=notice[1]))

        report = job.clip_verification_report

        if report is None:
            layout.addWidget(
                small_muted(
                    "Not checked yet. This runs by itself when Generate all scenes "
                    "finishes: it confirms every scene has a readable clip of the "
                    "right length, that no two scenes share the same footage, and "
                    "shows a still from each clip next to its narration."
                )
            )
            self._layout.addWidget(frame)

            return

        stale = report.clip_signature != clip_signature(job)
        layout.addWidget(self._verification_headline(report, stale=stale))

        # Scenes that need a look come first and in full; the ones that are
        # fine are tucked behind a button so a 100-scene project is not a
        # 100-row scroll. Every scene is still one click away.
        needs_attention = [
            r for r in report.scenes if r.severity != ClipVerificationSeverity.OK
        ]
        fine = [r for r in report.scenes if r.severity == ClipVerificationSeverity.OK]

        if needs_attention:
            layout.addWidget(subheading(f"Needs attention ({len(needs_attention)})"))
            layout.addWidget(
                ExpandableList(
                    [self._verification_row(r) for r in needs_attention],
                    visible_count=_CLIP_CHECK_PROBLEM_ROWS_VISIBLE,
                    noun="scenes needing attention",
                )
            )

        if fine:
            layout.addWidget(subheading(f"OK ({len(fine)})"))
            layout.addWidget(
                ExpandableList(
                    [self._verification_row(r) for r in fine],
                    visible_count=_CLIP_CHECK_OK_ROWS_VISIBLE,
                    noun="OK scenes",
                )
            )

        self._layout.addWidget(frame)

    @staticmethod
    def _verification_headline(
        report: ClipAttachmentVerificationReport, *, stale: bool
    ) -> QLabel:
        checked_at = report.verified_at.astimezone().strftime("%H:%M")
        total = len(report.scenes)

        if stale:
            return status_label(
                f"Out of date - the clips changed after this check ({checked_at}). "
                "Check again before trusting it.",
                role="warning",
            )

        if report.is_clean:
            return status_label(
                f"All {total} scene(s) have a readable clip of the right length and "
                f"no repeated footage (checked {checked_at}). Compare each still with "
                "its narration below.",
                role="success",
            )

        parts = [f"{report.ok_count} OK"]

        if report.warning_count:
            parts.append(f"{report.warning_count} to look at")

        if report.error_count:
            parts.append(f"{report.error_count} with a problem")

        return status_label(
            f"{total} scene(s): {', '.join(parts)} (checked {checked_at}).",
            role="error" if report.error_count else "warning",
        )

    @staticmethod
    def _verification_row(result: SceneClipVerification) -> QFrame:
        row_frame = QFrame()
        row_frame.setProperty("sceneRow", True)

        row_layout = QHBoxLayout(row_frame)
        row_layout.setContentsMargins(12, 8, 12, 8)
        row_layout.setSpacing(12)

        picture = QLabel()
        picture.setFixedWidth(176)
        picture.setAlignment(Qt.AlignmentFlag.AlignCenter)

        pixmap = QPixmap(result.thumbnail_file) if result.thumbnail_file else QPixmap()

        if pixmap.isNull():
            picture.setText("No preview")
            picture.setProperty("role", "small-muted")
            picture.setFixedHeight(99)
        else:
            picture.setPixmap(
                pixmap.scaledToWidth(176, Qt.TransformationMode.SmoothTransformation)
            )

        row_layout.addWidget(picture)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(3)

        lengths = (
            f"{result.actual_seconds:g}s of footage"
            if result.actual_seconds is not None
            else "length unknown"
        )

        if result.expected_seconds is not None:
            lengths += f" for {result.expected_seconds:g}s of narration"

        verdict = {
            ClipVerificationSeverity.OK: "OK",
            ClipVerificationSeverity.WARNING: "Look at this",
            ClipVerificationSeverity.ERROR: "Problem",
        }[result.severity]
        text_layout.addWidget(
            badge(
                f"#{result.scene_number} {result.scene_title} - {verdict}"
                + (f" - {result.provider}" if result.provider else "")
            )
        )
        text_layout.addWidget(small_muted(lengths))

        narration = result.narration

        if len(narration) > 160:
            narration = narration[:157] + "..."

        text_layout.addWidget(small_muted(narration))

        for reference in result.references:
            text_layout.addLayout(ClipWorkspaceView._reference_line(reference))

        for issue in result.issues:
            if issue.code in _REFERENCE_ISSUE_CODES:
                continue

            text_layout.addWidget(
                status_label(
                    issue.message,
                    role=(
                        "error"
                        if issue.severity == ClipVerificationSeverity.ERROR
                        else "warning"
                    ),
                )
            )

        row_layout.addLayout(text_layout, stretch=1)

        return row_frame

    @staticmethod
    def _reference_line(reference: SceneReferenceStatus) -> QHBoxLayout:
        """One character or place on screen: its reference picture (so it can be
        compared with the still beside it) and what became of it in this scene."""

        line = QHBoxLayout()
        line.setSpacing(8)

        picture = QLabel()
        picture.setFixedSize(44, 44)
        picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = (
            QPixmap(reference.reference_file) if reference.reference_file else QPixmap()
        )

        if pixmap.isNull():
            picture.setText("-")
            picture.setProperty("role", "small-muted")
        else:
            picture.setPixmap(
                pixmap.scaled(
                    44,
                    44,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

        line.addWidget(picture)

        kind = "character" if reference.is_person else "place"
        name = reference.name

        if reference.state == ReferenceUse.NO_REFERENCE:
            label: QLabel = status_label(
                f"{name} is on screen but has no reference picture yet - this "
                f"{kind} is held to the written description only.",
                role="warning",
            )
        elif reference.state == ReferenceUse.NOT_ATTACHED:
            label = status_label(
                f"{name} has a reference (from scene {reference.reference_scene}) "
                "but this scene was generated without it - they may not look the "
                "same as in the other scenes.",
                role="warning",
            )
        elif reference.state == ReferenceUse.SOURCE_SCENE:
            label = small_muted(
                f"{name} ({kind}) - this scene is where their reference was taken from"
            )
        elif reference.state == ReferenceUse.BEFORE_REFERENCE:
            label = small_muted(
                f"{name} ({kind}) - generated before a reference existed"
            )
        else:
            label = small_muted(f"{name} ({kind}) - reference attached")

        line.addWidget(label, stretch=1)

        return line

    def _handle_refresh_references(self) -> None:
        job = self._current_job()

        if job is None or job.id in self._refreshing_job_ids:
            return

        thread = QThread()
        worker = _ReferenceRefreshWorker(
            service=self._reference_refresh_service, job=job.model_copy(deep=True)
        )
        worker.moveToThread(thread)
        thread.job_id = job.id  # type: ignore[attr-defined]

        thread.started.connect(worker.run)
        worker.finished.connect(self._handle_refresh_finished)
        worker.failed.connect(self._handle_refresh_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._handle_refresh_thread_finished)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._refresh_threads[job.id] = (thread, worker)
        self._refreshing_job_ids.add(job.id)
        self._refresh_notices.pop(job.id, None)

        self._rebuild_card(job)

        thread.start()

    def _handle_refresh_finished(self, result: object) -> None:
        worker = self.sender()

        if not isinstance(worker, _ReferenceRefreshWorker):
            return

        job_id = worker.job_id
        self._refreshing_job_ids.discard(job_id)

        if not isinstance(result, tuple) or len(result) != 2:
            return

        refreshed, report = result
        job = self._job_store.get(job_id)

        if job is not None and isinstance(report, ReferenceRefreshReport):
            ReferenceRefreshService.apply_to(job, refreshed)
            self._job_store.add(job)
            self._refresh_notices[job_id] = (
                report.text(),
                "success" if report.replaced_count else "warning",
            )

        if job_id == self._job_id:
            self._on_change()

    def _handle_refresh_failed(self, message: str) -> None:
        worker = self.sender()

        if not isinstance(worker, _ReferenceRefreshWorker):
            return

        job_id = worker.job_id
        self._refreshing_job_ids.discard(job_id)
        self._refresh_notices[job_id] = (
            f"References could not be refreshed: {message}",
            "error",
        )

        if job_id == self._job_id:
            self._on_change()

    def _handle_refresh_thread_finished(self) -> None:
        thread = self.sender()
        job_id = getattr(thread, "job_id", None)

        if job_id is not None:
            self._refresh_threads.pop(job_id, None)

    def _handle_check_clips(self) -> None:
        job = self._current_job()

        if job is None or job.id in self._verifying_job_ids:
            return

        thread = QThread()
        worker = _ClipVerificationWorker(
            verifier=self._clip_verification_service,
            job=job.model_copy(deep=True),
        )
        worker.moveToThread(thread)
        thread.job_id = job.id  # type: ignore[attr-defined]

        thread.started.connect(worker.run)
        worker.finished.connect(self._handle_verification_finished)
        worker.failed.connect(self._handle_verification_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._handle_verification_thread_finished)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._verification_threads[job.id] = (thread, worker)
        self._verifying_job_ids.add(job.id)

        self._rebuild_card(job)

        thread.start()

    def _handle_verification_finished(self, report: object) -> None:
        worker = self.sender()

        if not isinstance(worker, _ClipVerificationWorker):
            return

        job_id = worker.job_id
        self._verifying_job_ids.discard(job_id)

        job = self._job_store.get(job_id)

        if job is not None and isinstance(report, ClipAttachmentVerificationReport):
            job.clip_verification_report = report
            self._job_store.add(job)

        if job_id == self._job_id:
            self._on_change()

    def _handle_verification_failed(self, message: str) -> None:
        worker = self.sender()

        if not isinstance(worker, _ClipVerificationWorker):
            return

        job_id = worker.job_id
        self._verifying_job_ids.discard(job_id)

        if job_id == self._job_id:
            show_recoverable_error(self, "Clip check failed", message)
            self._on_change()

    def _handle_verification_thread_finished(self) -> None:
        thread = self.sender()
        job_id = getattr(thread, "job_id", None)

        if job_id is not None:
            self._verification_threads.pop(job_id, None)

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

        completeness_service = SceneCompletenessService()
        report = completeness_service.check(job)
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

        account_combo = QComboBox()
        account_combo.setEnabled(not is_generating)
        self._populate_account_combo(account_combo, selected_profile_id=None)
        self._generate_all_account_combo = account_combo

        layout.addLayout(row(all_button, account_combo))

        for scene in sorted(job.scenes, key=lambda scene: scene.scene_number):
            entry = entries_by_scene.get(scene.scene_number)

            row_layout = QVBoxLayout()
            row_layout.setContentsMargins(0, 4, 0, 4)
            row_layout.setSpacing(2)

            row_layout.addWidget(
                small_muted(
                    f"Scene {scene.scene_number}: {scene.title}  \u00b7  "
                    f"{self._clip_length_text(job, scene)}"
                )
            )

            if entry is not None:
                row_layout.addWidget(
                    status_label(
                        f"{entry.status.value} - {entry.detail}",
                        role=_COMPLETENESS_STATUS_ROLE[entry.status],
                    )
                )

            # Multi-clip scene splitting (2026-09-29): a split scene's
            # entry above reports only its MOST RECENT sub-clip's
            # state - this breakdown gives an operator visibility into
            # which specific sub-clip is stuck, mirroring the Prompts
            # tab's own "Part X of Y" labeling for the same feature.
            # Read-only by design: Generate/Abandon/Retry below still
            # act on the whole scene, since generate_one() already
            # resumes a split scene from wherever it left off.
            sub_clip_statuses = completeness_service.sub_clip_statuses(
                job, scene.scene_number
            )

            for index, sub_clip_status in sub_clip_statuses:
                row_layout.addWidget(
                    status_label(
                        f"Part {index + 1} of {len(sub_clip_statuses)}: "
                        f"{sub_clip_status}",
                        role=_sub_clip_status_role(sub_clip_status),
                    )
                )

            if not sub_clip_statuses:
                plan_text = self._planned_split_text(job, scene)

                if plan_text is not None:
                    row_layout.addWidget(small_muted(plan_text))

            stuck_on_auth = self._auth_required_attempt(job, scene.scene_number)
            stuck_other = (
                self._other_stuck_attempt(job, scene.scene_number)
                if stuck_on_auth is None
                else None
            )

            if stuck_on_auth is not None:
                primary_button = button("Retry after login", variant="primary")
                primary_button.setEnabled(not is_generating)
                primary_button.clicked.connect(
                    lambda checked=False, number=scene.scene_number: (
                        self._handle_retry_scene_after_auth(number)
                    )
                )
            elif stuck_other is not None:
                primary_button = button("Abandon attempt", variant="danger")
                primary_button.setEnabled(not is_generating)
                primary_button.clicked.connect(
                    lambda checked=False, number=scene.scene_number: (
                        self._handle_abandon_stuck_attempt(number)
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

            has_resolved_clip = (
                entry is not None and entry.status == SceneCompletenessStatus.READY
            )
            remove_button = button("Remove", variant="danger")
            remove_button.setEnabled(not is_generating and has_resolved_clip)
            remove_button.clicked.connect(
                lambda checked=False, number=scene.scene_number: (
                    self._handle_remove_scene_clip(number)
                )
            )

            # Per-scene account picker (locked design, generalized to
            # both providers once Muse existed): "Auto" (None) keeps
            # today's priority-based routing unchanged; picking a
            # specific account routes that scene's next Generate click
            # through SceneGenerationDispatchService to whichever
            # provider that account actually belongs to.
            account_combo = QComboBox()
            account_combo.setEnabled(not is_generating)
            self._populate_account_combo(
                account_combo, selected_profile_id=scene.preferred_profile_id
            )
            account_combo.currentIndexChanged.connect(
                lambda index, combo=account_combo, number=scene.scene_number: (
                    self._handle_scene_preferred_profile_changed(
                        number, combo.itemData(index)
                    )
                )
            )

            # stretch_at_end (row()'s own default, True) is what keeps
            # these three compact and left-aligned - a real, found bug
            # in the original per-scene Upload button pass: passing
            # stretch_at_end=False here left nothing to absorb the
            # row's leftover width, so Qt's own layout gave it to the
            # buttons themselves instead, stretching them to fill the
            # whole card - confirmed by comparison against the
            # Dashboard's own "Continue Production"/"Delete Project"
            # row, which already uses this same row() helper's default
            # and renders compact.
            row_layout.addLayout(
                row(primary_button, upload_button, remove_button, account_combo)
            )

            layout.addLayout(row_layout)

        self._layout.addWidget(frame)

    @staticmethod
    def _auth_required_attempt(
        job: VideoJob, scene_number: int
    ) -> GoogleFlowGenerationAttempt | MuseGenerationAttempt | None:
        """
        The scene's stuck AUTH_REQUIRED attempt, if any - checked
        across every sub-clip index (a Phase 5 split scene's stuck
        attempt need not be clip_sequence_index=0), not just via
        SceneCompletenessService's own default-index lookup.

        Real-world finding, 2026-09-29: this used to check only
        job.flow_generation_attempts - once Muse existed as a second
        provider, a scene stuck on Muse's own AUTH_REQUIRED never got
        a "Retry after login" button at all. Checked across both
        ledgers now, same reasoning as
        SceneCompletenessService._latest_attempt_for_scene.
        """

        flow_attempt = next(
            (
                attempt
                for attempt in job.flow_generation_attempts
                if attempt.request.scene_number == scene_number
                and attempt.state == GoogleFlowGenerationState.AUTH_REQUIRED
            ),
            None,
        )

        if flow_attempt is not None:
            return flow_attempt

        return next(
            (
                attempt
                for attempt in job.muse_generation_attempts
                if attempt.request.scene_number == scene_number
                and attempt.state == MuseGenerationState.AUTH_REQUIRED
            ),
            None,
        )

    @staticmethod
    def _other_stuck_attempt(
        job: VideoJob, scene_number: int
    ) -> GoogleFlowGenerationAttempt | MuseGenerationAttempt | None:
        """
        A scene's stuck non-terminal attempt that ISN'T AUTH_REQUIRED
        (which already has its own "Retry after login" recovery path
        above) - e.g. UI_CHANGED, or a PLANNED attempt that never
        actually started. Checked across every sub-clip index, same
        reasoning as _auth_required_attempt.

        Real-world finding, 2026-09-29: this used to check only
        job.flow_generation_attempts - a scene whose latest attempt
        was a stuck, never-progressed Muse PLANNED attempt (submit()
        raised before ever reaching replace_attempt()) showed a plain
        "Generate" button instead of "Abandon attempt", and clicking
        it was a silent no-op (_drive_to_terminal only resubmits a
        None/orphaned-READY/FAILED/QC_FAILED attempt - a lone PLANNED
        attempt is none of those). Checked across both ledgers now.
        """

        flow_attempt = next(
            (
                attempt
                for attempt in job.flow_generation_attempts
                if attempt.request.scene_number == scene_number
                and not is_terminal_state(attempt.state)
                and attempt.state != GoogleFlowGenerationState.AUTH_REQUIRED
            ),
            None,
        )

        if flow_attempt is not None:
            return flow_attempt

        return next(
            (
                attempt
                for attempt in job.muse_generation_attempts
                if attempt.request.scene_number == scene_number
                and not muse_is_terminal_state(attempt.state)
                and attempt.state != MuseGenerationState.AUTH_REQUIRED
            ),
            None,
        )

    def _populate_account_combo(
        self, combo: QComboBox, *, selected_profile_id: str | None
    ) -> None:
        """
        Fill an account-picker combo with "Auto" plus every ENABLED
        EXTERNAL_UI_VIDEO account across both providers (Google Flow
        and Muse) - enabled_only, not usable_only, so a temporarily
        unhealthy/cooldown account still appears and is selectable,
        surfacing a clear error at Generate time (SceneGenerationDispatchService
        -> the account router's own preferred_profile_id validation)
        rather than silently disappearing from the list.

        Each item's data is the real profile_id (or None for "Auto") -
        read back via currentData()/itemData(), never the display
        text, so renaming a provider's own display_name can never
        silently change which account gets selected.
        """

        combo.clear()
        combo.addItem("Auto", None)

        if self._provider_registry is None:
            return

        for profile in self._provider_registry.list_by_category(
            ProviderCategory.EXTERNAL_UI_VIDEO, enabled_only=True
        ):
            combo.addItem(
                f"{profile.provider_name} — {profile.display_name}",
                profile.profile_id,
            )

        if selected_profile_id is not None:
            index = combo.findData(selected_profile_id)

            if index >= 0:
                combo.setCurrentIndex(index)

    @staticmethod
    def _clip_length_text(job: VideoJob, scene: Scene) -> str:
        """How long this scene's clip is: the real length once a clip exists
        ("clip 7s", or "clips 7s + 7s = 14s" for a split scene), otherwise the
        length it is planned to be generated at, so the row says how long the
        picture will run before a credit is spent. The narration length is added
        once it is known - it is what the clip has to cover."""

        narration = scene.real_narration_duration_seconds
        narration_text = f"  \u00b7  narration {narration:.1f}s" if narration else ""
        clips = sorted(
            (c for c in job.video_clips if c.scene_number == scene.scene_number),
            key=lambda c: c.clip_sequence_index,
        )

        if clips:
            lengths = [clip.duration_seconds for clip in clips]

            if len(lengths) == 1:
                return f"clip {lengths[0]}s{narration_text}"

            return (
                f"clips {' + '.join(f'{n}s' for n in lengths)} = "
                f"{sum(lengths)}s{narration_text}"
            )

        provider = resolve_scene_video_provider(job, scene)
        rules = rules_for(provider)
        seconds = (
            narration
            if narration is not None
            else float(scene.estimated_duration_seconds)
        )

        if rules.needs_split(seconds):
            parts = [
                muse_target_seconds(part) if provider == VideoProvider.MUSE else part
                for part in rules.plan_clips(seconds)
            ]
            planned = " + ".join(f"{part:.0f}s" for part in parts)

            return f"planned {planned}{narration_text}"

        return f"planned {rules.single_clip_seconds(seconds):.0f}s{narration_text}"

    @staticmethod
    def _planned_split_text(job: VideoJob, scene: Scene) -> str | None:
        """For a scene that has not started: say up front that it will be several
        clips. The Prompts tab already shows one prompt per part, while this row has
        one Generate button - which makes every part, in order, so without this line
        it looked as if the second prompt had no clip."""

        provider = resolve_scene_video_provider(job, scene)
        rules = rules_for(provider)
        seconds = (
            scene.real_narration_duration_seconds
            if scene.real_narration_duration_seconds is not None
            else float(scene.estimated_duration_seconds)
        )

        if not rules.needs_split(seconds):
            return None

        parts = [
            muse_target_seconds(part) if provider == VideoProvider.MUSE else part
            for part in rules.plan_clips(seconds)
        ]

        return (
            f"Will be generated as {len(parts)} clips "
            f"({' + '.join(f'{part:.0f}s' for part in parts)}) - one Generate makes "
            "all of them, in order."
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

    def _handle_abandon_stuck_attempt(
        self, scene_number: int, *, force: bool = False
    ) -> None:
        job = self._current_job()

        if job is None:
            return

        service = self._scene_video_generation_service

        if service is None:
            return

        try:
            service.abandon_stuck_attempt(job, scene_number, force=force)
        except (
            GoogleFlowAttemptCreditSensitiveError,
            MuseAttemptCreditSensitiveError,
        ) as error:
            confirmation = QMessageBox.question(
                self,
                "Abandon stuck generation attempt",
                f"{error}\n\nAbandon anyway?",
            )

            if confirmation == QMessageBox.StandardButton.Yes:
                self._handle_abandon_stuck_attempt(scene_number, force=True)

            return
        except ValueError as error:
            QMessageBox.warning(self, "Could not abandon attempt", str(error))

            return

        self._job_store.add(job)
        self._on_change()

    def _handle_scene_preferred_profile_changed(
        self, scene_number: int, profile_id: object
    ) -> None:
        job = self._current_job()

        if job is None:
            return

        scene = next((s for s in job.scenes if s.scene_number == scene_number), None)

        if scene is None:
            return

        # QComboBox.itemData() is typed Any at the Qt binding level -
        # this combo's own items only ever carry None or a str (see
        # _populate_account_combo), so this narrows it back for mypy
        # without changing behavior.
        scene.preferred_profile_id = profile_id if isinstance(profile_id, str) else None

        self._job_store.add(job)
        self._on_change()

    def _handle_generate_all_scene_videos(self) -> None:
        job = self._current_job()

        if job is None:
            return

        forced_profile_id: str | None = None

        if self._generate_all_account_combo is not None:
            data = self._generate_all_account_combo.currentData()
            forced_profile_id = data if isinstance(data, str) else None

        self._execute_scene_generation(
            job, scene_number=None, forced_profile_id=forced_profile_id
        )

    def _execute_scene_generation(
        self,
        job: VideoJob,
        *,
        scene_number: int | None,
        retry_after_auth: bool = False,
        forced_profile_id: str | None = None,
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
            forced_profile_id=forced_profile_id,
            verifier=self._clip_verification_service,
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
        scene_rows: list[QWidget] = []

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

            scene_rows.append(row)

        layout.addWidget(
            ExpandableList(scene_rows, visible_count=_SCENE_ROWS_VISIBLE, noun="scenes")
        )

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

    def _handle_remove_scene_clip(self, scene_number: int) -> None:
        job = self._current_job()

        if job is None:
            return

        self._bulk_ingestion_service.remove_scene_clip(
            job=job, scene_number=scene_number
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
