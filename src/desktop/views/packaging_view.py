from __future__ import annotations

from collections.abc import Callable
from typing import Protocol
from uuid import UUID

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.desktop.job_store import JobStore
from src.desktop.recovery_dialog import show_recoverable_error
from src.desktop.widgets import (
    button,
    card,
    muted,
    small_muted,
    status_label,
    subheading,
)
from src.models.approval import ApprovalPolicy
from src.models.content_decision_record import DecisionCategory
from src.models.final_export import FinalExportPackage
from src.models.seo import SEOPackage, SEOStatus
from src.models.thumbnail import ThumbnailArtifact, ThumbnailArtifactStatus
from src.models.video_job import VideoJob
from src.services.approval_gate_service import ApprovalGateService
from src.services.final_export.final_export_service import FinalExportService
from src.services.seo.seo_context_builder import SEOContextBuilder
from src.services.seo.seo_package_service import SEOPackageService
from src.services.thumbnail.thumbnail_package_service import ThumbnailPackageService

_LEFT = Qt.AlignmentFlag.AlignLeft


def _resolved_genre_id(job: VideoJob) -> str:
    """
    The genre identity SEO/thumbnail generation should describe.

    MRA-PRE-4 (Pre-Installer Master Audit, genre/audience/brand
    anti-drift audit) finding: `ScriptLock.genre_id` exists
    specifically to snapshot "topic, angle, target duration,
    genre/profile references" at the moment a script is frozen (see
    that model's own docstring), but had zero readers anywhere in the
    codebase - `job.genre_id` has no guard preventing a change after
    Script Lock (Content Studio's own "Project settings" card allows
    it freely), so SEO/thumbnail generation calling `build(...,
    genre_id=job.genre_id)` would silently describe a LOCKED script
    using a genre the script itself was never actually written in, if
    a person changed the project's genre after locking. Preferring the
    locked snapshot once one exists closes that gap; a lock with no
    genre_id (one built before this field existed) or no lock at all
    (SEO/thumbnail can be generated for a Script-Intake project with
    no lock) honestly falls back to the live field, matching every
    other optional-snapshot field's own established convention in this
    codebase.
    """

    if job.script_lock is not None and job.script_lock.genre_id is not None:
        return job.script_lock.genre_id

    return job.genre_id


def _script_is_approved(job: VideoJob) -> bool:
    """
    Whether this project has a finalized script ready to feed SEO/
    thumbnail generation.

    MRA-PRE-3 (Pre-Installer Master Audit) finding: this used to check
    only the legacy `job.script.status`, so both the SEO and thumbnail
    cards permanently showed "Requires an approved script." for every
    ContentIntelligencePipeline-produced project - that pipeline never
    populates `job.script`, only `job.generated_script` + `job.script_lock`
    once Script Lock happens. Script Lock is that pipeline's own hard
    "approved and frozen" boundary (see src/models/script_lock.py), the
    direct equivalent of `ScriptStatus.APPROVED` on the legacy field -
    mirrors the same reconciliation SEOContextBuilder.build() now does.
    """

    if job.generated_script is not None:
        return job.script_lock is not None

    return job.script is not None and job.script.status.value == "approved"


class _PackageProvenance(Protocol):
    """
    The dependency-tracking fields SEOPackage and ThumbnailArtifact
    both carry identically (Step 2, SEO-3/SEO-4) - a structural type
    so the staleness banner can accept either without depending on
    both concrete models or duplicating the check.
    """

    source_script_lock_hash: str | None
    source_genre_id: str | None
    source_target_country: str | None
    source_language: str | None
    source_scene_count: int | None


class PackagingView(QWidget):
    """
    Packaging: SEO metadata, thumbnail, and final publish-ready export.

    Final export only becomes available once a render actually
    succeeds, and requires both an SEO package and a thumbnail -
    building it any earlier would package an incomplete or missing
    video.
    """

    def __init__(
        self,
        *,
        job_store: JobStore,
        seo_package_service: SEOPackageService,
        thumbnail_package_service: ThumbnailPackageService,
        final_export_service: FinalExportService,
        on_change: Callable[[], None],
        approval_gate_service: ApprovalGateService | None = None,
    ) -> None:
        super().__init__()

        self._job_store = job_store
        self._seo_package_service = seo_package_service
        self._thumbnail_package_service = thumbnail_package_service
        self._final_export_service = final_export_service
        self._on_change = on_change
        self._approval_gate_service = approval_gate_service or ApprovalGateService()
        self._job_id: UUID | None = None

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

        self._build_seo_card(job)
        self._build_thumbnail_card(job)
        self._build_final_export_card(job)

    def _build_seo_card(self, job: VideoJob) -> None:
        frame, layout = card("SEO package", icon_name="tag")

        assert self._job_id is not None

        seo_package = self._job_store.get_seo_package(self._job_id)

        script_approved = _script_is_approved(job)

        if seo_package is not None:
            layout.addWidget(subheading(seo_package.selected_title or ""))
            layout.addWidget(muted(seo_package.description))
            layout.addWidget(small_muted(f"Tags: {', '.join(seo_package.tags)}"))
            layout.addWidget(small_muted(f"Hashtags: {' '.join(seo_package.hashtags)}"))
            layout.addWidget(
                small_muted(f"Version {seo_package.version_number}"),
            )

            self._build_dependency_staleness_banners(
                layout,
                job=job,
                provenance=seo_package,
            )

            self._build_review_status_row(
                layout,
                status_value=seo_package.status.value,
                on_approve=self._handle_approve_seo,
                on_reject=self._handle_reject_seo,
            )

            if script_approved:
                audience_getter = self._build_audience_widget(layout, job)

                regenerate_button = button("Regenerate SEO package", icon_name="tag")
                regenerate_button.clicked.connect(
                    lambda: self._handle_generate_seo(
                        audience_getter(),
                        previous_package=seo_package,
                    ),
                )
                layout.addWidget(regenerate_button, alignment=_LEFT)
        elif script_approved:
            layout.addWidget(small_muted("Not generated yet."))

            audience_getter = self._build_audience_widget(layout, job)

            generate_button = button(
                "Generate SEO package", variant="primary", icon_name="tag"
            )
            generate_button.clicked.connect(
                lambda: self._handle_generate_seo(audience_getter()),
            )
            layout.addWidget(generate_button, alignment=_LEFT)
        else:
            layout.addWidget(small_muted("Requires an approved script."))

        self._layout.addWidget(frame)

    def _build_thumbnail_card(self, job: VideoJob) -> None:
        frame, layout = card("Thumbnail", icon_name="image")

        assert self._job_id is not None

        thumbnail = self._job_store.get_thumbnail(self._job_id)

        script_approved = _script_is_approved(job)

        if thumbnail is not None:
            layout.addWidget(subheading(thumbnail.concept.hook_text))
            layout.addWidget(
                small_muted(f"Source: {thumbnail.image_source_type.value}")
            )
            layout.addWidget(small_muted(f"File: {thumbnail.file_path}"))
            layout.addWidget(
                small_muted(f"Version {thumbnail.version_number}"),
            )

            self._build_dependency_staleness_banners(
                layout,
                job=job,
                provenance=thumbnail,
            )

            self._build_review_status_row(
                layout,
                status_value=thumbnail.status.value,
                on_approve=self._handle_approve_thumbnail,
                on_reject=self._handle_reject_thumbnail,
            )

            if script_approved:
                audience_getter = self._build_audience_widget(layout, job)

                regenerate_button = button("Regenerate thumbnail", icon_name="image")
                regenerate_button.clicked.connect(
                    lambda: self._handle_generate_thumbnail(
                        audience_getter(),
                        previous_artifact=thumbnail,
                    ),
                )
                layout.addWidget(regenerate_button, alignment=_LEFT)
        elif script_approved:
            layout.addWidget(small_muted("Not generated yet."))

            audience_getter = self._build_audience_widget(layout, job)

            generate_button = button(
                "Generate thumbnail", variant="primary", icon_name="image"
            )
            generate_button.clicked.connect(
                lambda: self._handle_generate_thumbnail(audience_getter()),
            )
            layout.addWidget(generate_button, alignment=_LEFT)
        else:
            layout.addWidget(small_muted("Requires an approved script."))

        self._layout.addWidget(frame)

    @staticmethod
    def _build_audience_widget(
        layout: QVBoxLayout,
        job: VideoJob,
    ) -> Callable[[], str | None]:
        """
        Step 2 (SEO, Thumbnail & Publishing Reconciliation), SEO-2:
        "Make publishing metadata consume canonical creative/audience
        authority without re-inference." When this project already
        has a canonical audience promise (Content Studio Redesign,
        Phase 6), show it read-only and let SEOContextBuilder resolve
        it automatically - no free-text box for a person to re-guess
        an audience the project has already established. Only a
        project with no audience promise (e.g. an imported Script
        Intake project) falls back to the original free-text entry.

        Returns a zero-argument getter rather than the resolved value
        directly, so a "Regenerate" button built once at refresh time
        still reads whatever is currently in the fallback box at the
        moment it's clicked.
        """

        if job.audience_promise is not None:
            layout.addWidget(
                small_muted(
                    "Target audience: "
                    f"{job.audience_promise.target_audience} "
                    "(from Audience & Creative Strategy)"
                )
            )

            return lambda: None

        audience_input = QLineEdit("General audience")
        layout.addWidget(audience_input)

        return audience_input.text

    @staticmethod
    def _build_dependency_staleness_banners(
        layout: QVBoxLayout,
        *,
        job: VideoJob,
        provenance: _PackageProvenance,
    ) -> None:
        """
        Step 2 (SEO, Thumbnail & Publishing Reconciliation), SEO-4:
        "Define dependency graph for title, description, chapters,
        thumbnail copy, locale and final render duration... Material
        production changes must stale only affected publishing
        artifacts." A single script-content hash cannot catch every
        dependency this phase names - genre and locale can each
        change independently of the script's own text - so each
        tracked dependency is compared independently, naming exactly
        what moved rather than one coarse "something changed."

        Silent when nothing to compare against exists yet, or every
        tracked dependency still matches the job's current state.
        """

        if job.script_lock is not None:
            current_hash = job.script_lock.script_content_hash

            if provenance.source_script_lock_hash is None:
                layout.addWidget(
                    status_label(
                        "Built before the script was locked - "
                        "regenerate to bind it to the current script.",
                        role="warning",
                    )
                )
            elif provenance.source_script_lock_hash != current_hash:
                layout.addWidget(
                    status_label(
                        "Stale: the script has changed since this "
                        "was built. Regenerate to match the current "
                        "script.",
                        role="warning",
                    )
                )

        if (
            provenance.source_genre_id is not None
            and provenance.source_genre_id != job.genre_id
        ):
            layout.addWidget(
                status_label(
                    "Stale: the project's genre has changed since " "this was built.",
                    role="warning",
                )
            )

        if provenance.source_target_country is not None and (
            provenance.source_target_country != job.target_country
            or provenance.source_language != job.language
        ):
            layout.addWidget(
                status_label(
                    "Stale: the target country/language has changed "
                    "since this was built.",
                    role="warning",
                )
            )

        if (
            provenance.source_scene_count is not None
            and provenance.source_scene_count != len(job.scenes)
        ):
            layout.addWidget(
                status_label(
                    "Stale: the scene count has changed since this " "was built.",
                    role="warning",
                )
            )

    @staticmethod
    def _build_review_status_row(
        layout: QVBoxLayout,
        *,
        status_value: str,
        on_approve: Callable[[], None],
        on_reject: Callable[[], None],
    ) -> None:
        """
        Step 2 (SEO, Thumbnail & Publishing Reconciliation), SEO-5:
        "Provide coherent review/approval card and history." Approving
        or rejecting here directly sets the package's own status - a
        deliberately simpler, more direct mechanism than routing
        through the generic cross-pipeline pending-decision banner
        elsewhere (Content Studio's Activity History), since a person
        is already looking at exactly the artifact in question. Every
        transition is still recorded to the same shared
        job.content_decisions ledger (see _handle_approve_seo etc.)
        for a unified audit trail - "shared audit primitives" without
        a second competing approval-state machine.
        """

        role = {"approved": "success", "rejected": "error"}.get(status_value, "warning")

        layout.addWidget(
            status_label(f"Review status: {status_value}", role=role),
        )

        if status_value != "under_review":
            return

        approve_button = button("Approve", variant="primary", icon_name="check")
        approve_button.clicked.connect(on_approve)
        layout.addWidget(approve_button, alignment=_LEFT)

        reject_button = button("Reject")
        reject_button.clicked.connect(on_reject)
        layout.addWidget(reject_button, alignment=_LEFT)

    def _build_final_export_card(self, job: VideoJob) -> None:
        frame, layout = card("Final export", icon_name="export")

        assert self._job_id is not None

        final_export = self._job_store.get_final_export(self._job_id)
        render_result = self._job_store.get_render_result(self._job_id)
        seo_package = self._job_store.get_seo_package(self._job_id)
        thumbnail = self._job_store.get_thumbnail(self._job_id)

        if final_export is not None:
            status_role = (
                "success" if final_export.status.value == "approved" else "warning"
            )

            layout.addWidget(
                status_label(f"Status: {final_export.status.value}", role=status_role)
            )
            layout.addWidget(small_muted(f"Video: {final_export.final_video_path}"))
            layout.addWidget(
                small_muted(f"Export directory: {final_export.export_directory}")
            )

            self._build_qc_summary(layout, final_export)

            actions_row_widgets: list[QWidget] = []

            open_folder_button = button(
                "Open output folder",
                icon_name="folder",
            )
            open_folder_button.clicked.connect(
                lambda: self._handle_open_output_folder(final_export),
            )
            actions_row_widgets.append(open_folder_button)

            if final_export.manifest_path is not None:
                copy_manifest_button = button(
                    "Copy manifest path",
                )
                copy_manifest_button.clicked.connect(
                    lambda: self._handle_copy_manifest_path(final_export),
                )
                actions_row_widgets.append(copy_manifest_button)

            for action_widget in actions_row_widgets:
                layout.addWidget(action_widget, alignment=_LEFT)
        elif render_result is not None and render_result.success:
            if seo_package is not None and thumbnail is not None:
                layout.addWidget(small_muted("Not built yet."))

                export_button = button(
                    "Build final export package",
                    variant="primary",
                    icon_name="export",
                )
                export_button.clicked.connect(self._handle_build_final_export)
                layout.addWidget(export_button, alignment=_LEFT)
            else:
                layout.addWidget(
                    small_muted("Requires an SEO package and a thumbnail."),
                )
        else:
            layout.addWidget(
                small_muted("Requires a successful render (see Render Workspace).")
            )

        self._layout.addWidget(frame)

    def _build_qc_summary(
        self,
        layout: QVBoxLayout,
        final_export: FinalExportPackage,
    ) -> None:
        """
        Show the Final Package screen's QC summary.

        Re-runs the same, cheap, deterministic (no LLM/network calls)
        validation the build step already ran, so the summary always
        reflects the package's current on-disk state rather than a
        stale snapshot from whenever it was last built.
        """

        validation = self._final_export_service.validation_service.validate(
            final_export
        )

        if validation.is_valid and not validation.has_warnings:
            layout.addWidget(status_label("QC: all checks passed.", role="success"))
            return

        for issue in validation.errors:
            layout.addWidget(status_label(f"QC error: {issue.message}", role="error"))

        for issue in validation.warnings:
            layout.addWidget(
                status_label(f"QC warning: {issue.message}", role="warning")
            )

    def _handle_open_output_folder(
        self,
        final_export: FinalExportPackage,
    ) -> None:
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(final_export.export_directory),
        )

    def _handle_copy_manifest_path(
        self,
        final_export: FinalExportPackage,
    ) -> None:
        if final_export.manifest_path is None:
            return

        clipboard = QApplication.clipboard()

        if clipboard is not None:
            clipboard.setText(final_export.manifest_path)

    def _handle_generate_seo(
        self,
        target_audience: str | None,
        *,
        previous_package: SEOPackage | None = None,
    ) -> None:
        job = self._current_job()

        if job is None:
            return

        try:
            result = self._seo_package_service.build(
                job,
                genre_id=_resolved_genre_id(job),
                target_audience=target_audience,
                previous_package=previous_package,
            )
        except (RuntimeError, ValueError) as error:
            self._record_error(
                job,
                f"SEO generation failed: {error}",
                on_retry=lambda: self._handle_generate_seo(
                    target_audience,
                    previous_package=previous_package,
                ),
            )

            return

        assert self._job_id is not None

        package = result.package

        if job.approval_policy.policy_for("publishing") == ApprovalPolicy.AUTO:
            package = package.model_copy(update={"status": SEOStatus.APPROVED})

        self._approval_gate_service.record_event(
            job=job,
            stage="seo",
            summary=(f"SEO package generated (version {package.version_number})."),
            category=DecisionCategory.GENERATION,
        )

        self._job_store.set_seo_package(self._job_id, package)
        self._on_change()

    def _handle_approve_seo(self) -> None:
        self._resolve_seo_review(SEOStatus.APPROVED, "approved")

    def _handle_reject_seo(self) -> None:
        self._resolve_seo_review(SEOStatus.REJECTED, "rejected")

    def _resolve_seo_review(
        self,
        status: SEOStatus,
        verb: str,
    ) -> None:
        job = self._current_job()

        if job is None or self._job_id is None:
            return

        package = self._job_store.get_seo_package(self._job_id)

        if package is None:
            return

        resolved = package.model_copy(update={"status": status})

        self._approval_gate_service.record_event(
            job=job,
            stage="seo",
            summary=f"SEO package {verb}.",
            category=DecisionCategory.APPROVAL,
        )

        self._job_store.set_seo_package(self._job_id, resolved)
        self._on_change()

    def _handle_generate_thumbnail(
        self,
        target_audience: str | None,
        *,
        previous_artifact: ThumbnailArtifact | None = None,
    ) -> None:
        job = self._current_job()

        if job is None:
            return

        try:
            context = SEOContextBuilder().build(
                job,
                genre_id=_resolved_genre_id(job),
                target_audience=target_audience,
            )

            result = self._thumbnail_package_service.build(
                context,
                project_id=job.project_name,
                previous_artifact=previous_artifact,
            )
        except (RuntimeError, ValueError) as error:
            self._record_error(
                job,
                f"Thumbnail generation failed: {error}",
                on_retry=lambda: self._handle_generate_thumbnail(
                    target_audience,
                    previous_artifact=previous_artifact,
                ),
            )

            return

        assert self._job_id is not None

        artifact = result.artifact

        if job.approval_policy.policy_for("publishing") == ApprovalPolicy.AUTO:
            artifact = artifact.model_copy(
                update={"status": ThumbnailArtifactStatus.APPROVED},
            )

        self._approval_gate_service.record_event(
            job=job,
            stage="thumbnail",
            summary=(f"Thumbnail generated (version {artifact.version_number})."),
            category=DecisionCategory.GENERATION,
        )

        self._job_store.set_thumbnail(self._job_id, artifact)
        self._on_change()

    def _handle_approve_thumbnail(self) -> None:
        self._resolve_thumbnail_review(ThumbnailArtifactStatus.APPROVED, "approved")

    def _handle_reject_thumbnail(self) -> None:
        self._resolve_thumbnail_review(ThumbnailArtifactStatus.REJECTED, "rejected")

    def _resolve_thumbnail_review(
        self,
        status: ThumbnailArtifactStatus,
        verb: str,
    ) -> None:
        job = self._current_job()

        if job is None or self._job_id is None:
            return

        artifact = self._job_store.get_thumbnail(self._job_id)

        if artifact is None:
            return

        resolved = artifact.model_copy(update={"status": status})

        self._approval_gate_service.record_event(
            job=job,
            stage="thumbnail",
            summary=f"Thumbnail {verb}.",
            category=DecisionCategory.APPROVAL,
        )

        self._job_store.set_thumbnail(self._job_id, resolved)
        self._on_change()

    def _handle_build_final_export(self) -> None:
        job = self._current_job()

        if job is None:
            return

        assert self._job_id is not None

        render_result = self._job_store.get_render_result(self._job_id)
        seo_package = self._job_store.get_seo_package(self._job_id)
        thumbnail = self._job_store.get_thumbnail(self._job_id)

        if render_result is None or seo_package is None or thumbnail is None:
            return

        try:
            result = self._final_export_service.build(
                render_result,
                project_id=job.project_name,
                resolution="1920x1080",
                frame_rate=30,
                seo_package=seo_package,
                thumbnail_artifact=thumbnail,
            )
        except (RuntimeError, ValueError) as error:
            self._record_error(
                job,
                f"Final export failed: {error}",
                on_retry=self._handle_build_final_export,
            )

            return

        self._job_store.set_final_export(self._job_id, result.package)
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
