from __future__ import annotations

from src.models.editorial_critique import EditorialCritique
from src.models.editorial_profile import EditorialProfile
from src.models.script_quality_report import ScriptQualityReport, ScriptQualityStatus


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
    ) -> ScriptQualityReport:
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
        )
