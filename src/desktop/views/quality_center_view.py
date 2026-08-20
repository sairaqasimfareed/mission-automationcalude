from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget

from src.desktop.job_store import JobStore
from src.desktop.widgets import badge, button, card, small_muted, status_label
from src.models.blocker import BlockerSeverity
from src.models.policy import PolicyComplianceReport, RiskLevel
from src.models.production_readiness import ReadinessState
from src.models.video_job import VideoJob
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

    def _current_job(self) -> VideoJob | None:
        if self._job_id is None:
            return None

        return self._job_store.get(self._job_id)
