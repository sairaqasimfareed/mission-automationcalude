from __future__ import annotations

from pydantic import field_validator

from src.models.base import MissionBaseModel


class StaleArtifact(MissionBaseModel):
    """
    One already-produced artifact whose upstream input has since
    changed, so it no longer reflects the job's current state.

    Non-destructive by design: recorded alongside the artifact rather
    than replacing or clearing it, so a stale render result, timeline,
    or clip list is still there to inspect - just flagged as no longer
    trustworthy as-is. See InvalidationService for how these are
    produced and cleared.
    """

    artifact: str
    reason: str
    triggered_by: str

    @field_validator("artifact", "reason", "triggered_by")
    @classmethod
    def clean_required_text(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Invalidation text cannot be empty.")

        return cleaned
