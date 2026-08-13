from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QWidget

from src.desktop.job_store import JobStore
from src.desktop.widgets import button, card, small_muted, status_label
from src.models.policy import PolicyComplianceReport, RiskLevel
from src.models.video_job import VideoJob
from src.services.policy_service import PolicyService

_LEFT = Qt.AlignmentFlag.AlignLeft

_RISK_ROLE = {
    RiskLevel.LOW: "success",
    RiskLevel.MEDIUM: "warning",
    RiskLevel.HIGH: "error",
    RiskLevel.CRITICAL: "error",
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

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 12, 0, 0)
        self._layout.setSpacing(16)

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

        self._build_policy_card(job)

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
