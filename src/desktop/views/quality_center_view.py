from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.desktop.job_store import JobStore
from src.desktop.widgets import badge, button, card, small_muted, status_label
from src.models.blocker import BlockerSeverity
from src.models.final_preview import FinalPreviewAction, FinalPreviewStatus
from src.models.policy import PolicyComplianceReport, RiskLevel
from src.models.production_readiness import ReadinessState
from src.models.video_job import VideoJob
from src.services.final_preview_service import FinalPreviewService
from src.services.policy_service import PolicyService
from src.services.production_readiness_service import ProductionReadinessService

_LEFT = Qt.AlignmentFlag.AlignLeft

_RISK_ROLE = {
    RiskLevel.LOW: "success",
    RiskLevel.MEDIUM: "warning",
    RiskLevel.HIGH: "error",
    RiskLevel.CRITICAL: "error",
}

_READINESS_ROLE = {
    ReadinessState.BLOCKED: "error",
    ReadinessState.READY_FOR_RENDER: "success",
    ReadinessState.READY_FOR_FINAL_EXPORT: "success",
    ReadinessState.COMPLETED: "success",
}

_BLOCKER_SEVERITY_ROLE = {
    BlockerSeverity.INFO: "warning",
    BlockerSeverity.WARNING: "warning",
    BlockerSeverity.BLOCKING: "error",
}

_FINAL_PREVIEW_STATUS_ROLE = {
    FinalPreviewStatus.PENDING: "warning",
    FinalPreviewStatus.APPROVED: "success",
    FinalPreviewStatus.RETURNED_TO_EDITING: "warning",
}

_FINAL_PREVIEW_ACTION_LABELS = {
    FinalPreviewAction.APPROVE_FINAL: "Approve final",
    FinalPreviewAction.RETURN_TO_EDITING: "Return to editing",
    FinalPreviewAction.REPLACE_SCENE: "Replace a scene",
    FinalPreviewAction.REGENERATE_AUDIO: "Regenerate audio",
}


class QualityCenterView(QWidget):
    """
    Quality & Policy Center: monetization and upload-readiness review.

    PolicyService already existed in the backend but was never wired
    into any UI or pipeline stage - this workspace is its first
    caller. Evaluation is a pure function of the job's current state
    (script/originality/error status), so it can be re-run at any
    point to see how upload readiness changes as content moves through
    the pipeline.
    """

    def __init__(
        self,
        *,
        job_store: JobStore,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__()

        self._job_store = job_store
        self._on_change = on_change
        self._job_id: UUID | None = None
        self._policy_service = PolicyService()
        self._readiness_service = ProductionReadinessService()
        self._final_preview_service = FinalPreviewService()

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

        self._build_readiness_card(job)
        self._build_checklist_card(job)
        self._build_final_preview_card(job)
        self._build_policy_card(job)

    def _build_readiness_card(self, job: VideoJob) -> None:
        """
        The single centralized readiness answer (ProductionReadinessService)
        - every blocker it reports traces to a real, currently-unmet
        condition on this job, not a duplicated ad hoc check.
        """

        frame, layout = card("Production readiness", icon_name="dashboard")

        report = self._readiness_service.evaluate(job)

        layout.addWidget(
            status_label(
                report.state.value.replace("_", " "),
                role=_READINESS_ROLE[report.state],
            )
        )

        if not report.blockers:
            layout.addWidget(small_muted("No blockers."))
            self._layout.addWidget(frame)

            return

        for blocker in report.blockers:
            layout.addWidget(badge(f"{blocker.stage} · {blocker.severity.value}"))
            layout.addWidget(
                status_label(
                    blocker.message,
                    role=_BLOCKER_SEVERITY_ROLE[blocker.severity],
                )
            )

            if blocker.recovery_action:
                layout.addWidget(small_muted(blocker.recovery_action))

        self._layout.addWidget(frame)

    def _build_checklist_card(self, job: VideoJob) -> None:
        """
        Consolidated post-render readiness summary.

        Render success, SEO, thumbnail, the policy check, and final
        export each live in their own workspace - this pulls all five
        into one place instead of requiring a separate check in each.
        """

        frame, layout = card("Post-render checklist", icon_name="check-circle")

        assert self._job_id is not None

        render_result = self._job_store.get_render_result(self._job_id)
        render_ok = render_result is not None and render_result.success

        seo_package = self._job_store.get_seo_package(self._job_id)
        thumbnail = self._job_store.get_thumbnail(self._job_id)
        final_export = self._job_store.get_final_export(self._job_id)

        checks = (
            ("Render", render_ok),
            ("SEO package", seo_package is not None),
            ("Thumbnail", thumbnail is not None),
            ("Quality and policy check", job.policy_report is not None),
            ("Final export", final_export is not None),
        )

        for label, passed in checks:
            layout.addWidget(
                status_label(
                    f"{label}: {'done' if passed else 'not done'}",
                    role="success" if passed else "warning",
                )
            )

        ready_for_export = (
            render_ok and seo_package is not None and thumbnail is not None
        )

        if final_export is not None:
            layout.addWidget(
                status_label("Final export already built.", role="success")
            )
        elif ready_for_export:
            layout.addWidget(
                status_label(
                    "Ready to build the final export package - see Packaging.",
                    role="success",
                )
            )
        else:
            layout.addWidget(
                small_muted(
                    "Not ready for final export yet - see the items marked "
                    "'not done' above."
                )
            )

        self._layout.addWidget(frame)

    def _build_final_preview_card(self, job: VideoJob) -> None:
        """
        Review the completed render and decide: approve it as final,
        or send it back for more editing - bound to the exact render
        identity (RenderIdentityService) it was created from, so an
        approval that no longer matches the current render is caught
        rather than silently trusted forever.
        """

        frame, layout = card("Final preview", icon_name="check-circle")

        if job.render_result is None or not job.render_result.success:
            layout.addWidget(
                small_muted("Render a video first - see Render Workspace.")
            )
            self._layout.addWidget(frame)

            return

        latest = self._final_preview_service.latest_preview(job)

        if latest is not None:
            layout.addWidget(
                status_label(
                    latest.status.value.replace("_", " "),
                    role=_FINAL_PREVIEW_STATUS_ROLE[latest.status],
                )
            )
            layout.addWidget(small_muted(f"Output: {latest.output_file}"))

            if latest.status == FinalPreviewStatus.APPROVED:
                is_current = self._final_preview_service.is_current(job)
                layout.addWidget(
                    status_label(
                        (
                            "Still matches the current render."
                            if is_current
                            else "The render has changed since this was approved."
                        ),
                        role="success" if is_current else "error",
                    )
                )

        if latest is None or latest.status != FinalPreviewStatus.PENDING:
            create_button = button(
                (
                    "Create final preview"
                    if latest is None
                    else "Create a new final preview"
                ),
                variant="primary",
                icon_name="check-circle",
            )
            create_button.clicked.connect(self._handle_create_final_preview)
            layout.addWidget(create_button, alignment=_LEFT)
        else:
            action_row = QHBoxLayout()
            action_row.setSpacing(6)

            for action, label in _FINAL_PREVIEW_ACTION_LABELS.items():
                action_button = button(
                    label,
                    variant=(
                        "primary"
                        if action == FinalPreviewAction.APPROVE_FINAL
                        else "ghost"
                    ),
                )
                action_button.clicked.connect(
                    lambda _checked=False, a=action: self._handle_resolve_final_preview(
                        a
                    )
                )
                action_row.addWidget(action_button)

            action_row.addStretch()
            layout.addLayout(action_row)

        self._layout.addWidget(frame)

    def _build_policy_card(self, job: VideoJob) -> None:
        frame, layout = card("Quality and policy check", icon_name="shield")

        run_button = button(
            "Run quality and policy check",
            variant="primary",
            icon_name="shield",
        )
        run_button.clicked.connect(self._handle_run_check)
        layout.addWidget(run_button, alignment=_LEFT)

        report = job.policy_report

        if report is None:
            layout.addWidget(small_muted("Not checked yet."))
            self._layout.addWidget(frame)

            return

        self._build_report(layout, report)
        self._layout.addWidget(frame)

    @staticmethod
    def _build_report(layout: QVBoxLayout, report: PolicyComplianceReport) -> None:
        layout.addWidget(
            status_label(
                "Upload ready" if report.upload_readiness else "Not upload ready",
                role="success" if report.upload_readiness else "error",
            )
        )

        for label, risk in (
            ("YouTube monetization", report.youtube_monetization_risk),
            ("Facebook monetization", report.facebook_monetization_risk),
            ("Copyright", report.copyright_risk),
            ("Reused content", report.reused_content_risk),
        ):
            layout.addWidget(
                status_label(
                    f"{label}: {risk.value}",
                    role=_RISK_ROLE[risk],
                )
            )

        if report.disclosure_required:
            layout.addWidget(
                status_label("Disclosure required for this content.", role="warning")
            )

        if report.notes:
            layout.addWidget(
                small_muted(
                    "Notes:\n" + "\n".join(f"- {note}" for note in report.notes)
                )
            )

    def _handle_run_check(self) -> None:
        job = self._current_job()

        if job is None:
            return

        self._policy_service.evaluate(job)
        self._on_change()

    def _handle_create_final_preview(self) -> None:
        job = self._current_job()

        if job is None:
            return

        try:
            self._final_preview_service.create_preview(job)
        except (RuntimeError, ValueError) as error:
            self._record_error(job, f"Could not create final preview: {error}")

            return

        self._on_change()

    def _handle_resolve_final_preview(self, action: FinalPreviewAction) -> None:
        job = self._current_job()

        if job is None:
            return

        try:
            self._final_preview_service.resolve(job, action)
        except ValueError as error:
            self._record_error(job, f"Could not resolve final preview: {error}")

            return

        self._on_change()

    def _current_job(self) -> VideoJob | None:
        if self._job_id is None:
            return None

        return self._job_store.get(self._job_id)

    def _record_error(self, job: VideoJob, message: str) -> None:
        job.errors.append(message)
        QMessageBox.warning(self, "Step failed", message)
        self._on_change()
