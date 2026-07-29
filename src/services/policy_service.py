from __future__ import annotations

from src.models.enums import ProductionMode
from src.models.originality import OriginalityStatus
from src.models.policy import (
    PolicyComplianceReport,
    RiskLevel,
)
from src.models.script import ScriptStatus
from src.models.video_job import VideoJob


class PolicyService:
    """Builds the final policy and monetization report for a VideoJob."""

    def evaluate(self, job: VideoJob) -> VideoJob:
        upload_readiness = True
        notes: list[str] = []

        youtube_risk = RiskLevel.LOW
        facebook_risk = RiskLevel.LOW
        copyright_risk = RiskLevel.LOW
        reused_content_risk = RiskLevel.LOW

        if job.script is None:
            upload_readiness = False
            notes.append("Script is missing.")
            youtube_risk = RiskLevel.HIGH
            facebook_risk = RiskLevel.HIGH

        elif job.script.status != ScriptStatus.APPROVED:
            upload_readiness = False
            notes.append("Script has not been approved.")
            youtube_risk = RiskLevel.HIGH
            facebook_risk = RiskLevel.HIGH

        if job.originality_review is None:
            upload_readiness = False
            notes.append("Originality review is missing.")
            reused_content_risk = RiskLevel.HIGH

        else:
            if job.originality_review.status != OriginalityStatus.APPROVED:
                upload_readiness = False
                notes.append("Originality review has not been approved.")
                reused_content_risk = RiskLevel.HIGH

            if job.originality_review.originality_score < 80:
                upload_readiness = False
                notes.append("Originality score is below the safe threshold.")
                reused_content_risk = RiskLevel.HIGH

            if job.originality_review.human_value_score < 75:
                upload_readiness = False
                notes.append("Human value score is below the safe threshold.")
                youtube_risk = RiskLevel.HIGH
                facebook_risk = RiskLevel.HIGH

        if job.errors:
            upload_readiness = False
            notes.extend(job.errors)

        if job.production_mode == ProductionMode.QUICK:
            upload_readiness = False
            notes.append(
                "Quick Mode output is prototype-only and cannot be upload-ready."
            )

        job.policy_report = PolicyComplianceReport(
            youtube_monetization_risk=youtube_risk,
            facebook_monetization_risk=facebook_risk,
            copyright_risk=copyright_risk,
            reused_content_risk=reused_content_risk,
            upload_readiness=upload_readiness,
            source_mode=job.production_mode,
            disclosure_required=False,
            notes=notes,
        )

        return job
