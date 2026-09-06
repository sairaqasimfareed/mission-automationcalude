from __future__ import annotations

from uuid import UUID

from src.models.editorial_critique import EditorialCritique
from src.models.editorial_profile import EditorialProfile
from src.models.generated_script import GeneratedScript
from src.models.script_quality_report import (
    FindingResolution,
    FindingResolutionAction,
    ScriptQualityReport,
    ScriptQualityStatus,
)


class ScriptQualityGateService:
    """
    Aggregates one EditorialCritique against its genre's quality
    thresholds into a pass/needs-revision/needs-review decision. Pure
    aggregation - no LLM call, no new scores invented here. Only
    gates on dimensions the critique actually scored, so a genre with
    no character_policy (whose critique never scored character_depth/
    payoff_strength at all) never fails a script for a dimension that
    was never meant to apply to it.
    """

    def evaluate(
        self,
        *,
        critique: EditorialCritique,
        editorial_profile: EditorialProfile,
        script: GeneratedScript | None = None,
        script_version_number: int | None = None,
    ) -> ScriptQualityReport:
        """
        script/script_version_number are optional so every pre-Phase-13
        caller/test keeps constructing a report exactly as before; the
        real ContentIntelligencePipeline call site always supplies both
        so the resulting report can be bound to an exact script
        version/hash.
        """

        declared_thresholds = editorial_profile.content_intelligence.quality_thresholds

        evaluated_thresholds = {
            dimension: threshold
            for dimension, threshold in declared_thresholds.items()
            if dimension in critique.dimension_scores
        }

        evaluated_scores = {
            dimension: critique.dimension_scores[dimension]
            for dimension in evaluated_thresholds
        }

        failed_dimensions = [
            dimension
            for dimension, threshold in evaluated_thresholds.items()
            if evaluated_scores[dimension] < threshold
        ]

        blocking_findings = critique.blocking_findings
        major_findings = critique.major_findings

        if blocking_findings or failed_dimensions:
            status = ScriptQualityStatus.NEEDS_REVISION
        elif major_findings:
            status = ScriptQualityStatus.EDITORIAL_REVIEW
        else:
            status = ScriptQualityStatus.APPROVED_FOR_PRODUCTION

        return ScriptQualityReport(
            topic=critique.topic,
            genre_id=editorial_profile.genre_id,
            dimension_scores=evaluated_scores,
            dimension_thresholds=evaluated_thresholds,
            failed_dimensions=failed_dimensions,
            blocking_findings=blocking_findings,
            major_findings=major_findings,
            status=status,
            script_version_number=script_version_number,
            script_content_hash=script.content_hash if script is not None else None,
        )

    @staticmethod
    def ignore_finding(
        *,
        report: ScriptQualityReport,
        finding_id: UUID,
        reason: str,
    ) -> ScriptQualityReport:
        """
        Record that a person chose to ignore one finding, with a
        reason - Phase 13: "Store ignored findings with user reason."
        Does not change the report's score/status: an ignored finding
        is still visible, just annotated, matching this codebase's
        append-only audit-trail philosophy.
        """

        matched = next(
            (finding for finding in report.all_findings if finding.id == finding_id),
            None,
        )

        if matched is None:
            raise ValueError(f"No finding {finding_id} exists on this report.")

        if not reason.strip():
            raise ValueError("Ignoring a finding requires a non-empty reason.")

        if report.resolution_for(matched.id) is not None:
            raise ValueError(f"Finding {finding_id} already has a resolution.")

        resolution = FindingResolution(
            finding_id=matched.id,
            action=FindingResolutionAction.IGNORED,
            reason=reason.strip(),
        )

        return report.model_copy(
            update={"resolutions": [*report.resolutions, resolution]}
        )
