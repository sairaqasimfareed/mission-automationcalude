from __future__ import annotations

from src.models.script_production_readiness import ScriptProductionReadinessReport
from src.models.video_job import VideoJob


class ScriptProductionReadinessService:
    """
    Content Studio Redesign, Phase 16: pure aggregation - no LLM call,
    no new scores invented. Reads directly off what already exists on
    the job, exactly like ScriptQualityGateService does for editorial
    quality.

    Deliberately named distinctly from the pre-existing, broader
    ProductionReadinessService (src/services/production_readiness_service.py)
    - see ScriptProductionReadinessReport's docstring for why these
    are two different, non-overlapping concepts.
    """

    @staticmethod
    def evaluate(job: VideoJob) -> ScriptProductionReadinessReport:
        unresolved_blocking = [
            ambiguity
            for ambiguity in job.production_ambiguities
            if ambiguity.is_blocking
        ]

        return ScriptProductionReadinessReport(
            has_continuity_bible=job.continuity_bible is not None,
            has_scenes=bool(job.scenes),
            scene_count=len(job.scenes),
            unresolved_blocking_ambiguities=unresolved_blocking,
        )
