from __future__ import annotations

from src.models.script_lock import ScriptLock, ScriptProvenance
from src.models.video_job import VideoJob
from src.services.invalidation_service import SCRIPT_CHANGE_DOWNSTREAM_FIELDS


class ScriptLockService:
    """
    Builds and validates a Script Lock record - Content Studio
    Redesign, Phase 14: "Create the hard immutable boundary between
    Content Production and Media Production."

    Deliberately does not itself flip ScriptVersion.locked (the
    pre-existing per-version lock flag ScriptVersionService already
    enforces everywhere a script mutation is attempted) - that's
    orchestration ContentIntelligencePipeline.run_script_lock()/
    run_script_unlock() perform, alongside this service's record-
    building/validation, matching how every other multi-service stage
    in this pipeline is composed.
    """

    @staticmethod
    def build_lock(
        *,
        job: VideoJob,
        provenance: ScriptProvenance = ScriptProvenance.INTERNAL,
        override_reason: str | None = None,
    ) -> ScriptLock:
        if job.generated_script is None or job.script_version_history is None:
            raise ValueError(
                "Locking requires a generated script and a version history."
            )

        report = job.script_quality_report
        has_override = bool(override_reason and override_reason.strip())

        if (
            report is not None
            and report.unresolved_blocking_findings
            and not has_override
        ):
            raise ValueError(
                "Cannot lock: unresolved blocking quality findings exist. "
                "Resolve or ignore them, or provide a non-empty "
                "override_reason to lock anyway."
            )

        current = job.script_version_history.current_version
        cleaned_override_reason = (
            override_reason.strip() if override_reason is not None else None
        )

        return ScriptLock(
            script_version_number=current.version_number,
            script_content_hash=job.generated_script.content_hash,
            provenance=provenance,
            quality_status=report.status if report is not None else None,
            override_reason=cleaned_override_reason or None,
        )

    @staticmethod
    def compute_unlock_impact(job: VideoJob) -> list[str]:
        """
        Which actual downstream production artifacts exist right now
        and would need regenerating after an unlock (spec: "Unlock
        impact analysis... lists actual dependent assets, not a
        generic message"). Reuses InvalidationService's own downstream
        field list - the same fields that get marked stale on a script
        change are exactly what "depends on this locked script."
        """

        impacted = []

        for field_name in SCRIPT_CHANGE_DOWNSTREAM_FIELDS:
            value = getattr(job, field_name, None)
            has_value = bool(value) if isinstance(value, list) else value is not None

            if has_value:
                impacted.append(field_name)

        return impacted
