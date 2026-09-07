from __future__ import annotations

from enum import Enum

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel
from src.models.script_quality_report import ScriptQualityStatus


class ScriptProvenance(str, Enum):
    """
    Where a locked script's content originally came from (Content
    Studio Redesign, Phase 14: "Lock provenance identifies internal vs
    external script origin"). INTERNAL is every script this app's own
    Content Production pipeline generated; EXTERNAL is an imported/
    approved script (Phase 15's Script Intake path).
    """

    INTERNAL = "internal"
    EXTERNAL = "external"


class ScriptLock(MissionBaseModel):
    """
    An immutable record of one Script Lock event - the hard boundary
    between Content Production and Media Production (Content Studio
    Redesign, Phase 14).

    created_at (inherited from MissionBaseModel) IS the lock
    timestamp - there is deliberately no separate locked_at field, so
    there is only ever one clock to disagree with itself.

    Binds to an exact script version/hash (spec: "Content hash/version
    binding") and snapshots the quality status at lock time, so a
    later quality re-evaluation of a *different* script version never
    retroactively changes what this lock attests to.

    Found via external audit: the Post-Script-Approval Production
    Plan's own Phase 0 explicitly names "topic, angle, target
    duration, genre/profile references" among what a lock must
    persist, alongside version/hash - this model originally carried
    only the latter. topic/target_duration_seconds/genre_id/angle are
    all optional, new, backward-compatible fields (matching this
    codebase's own established convention for every field ever added
    to a persisted model - see e.g. Scene.locked_script_hash,
    SEOPackage's provenance fields): a `None` here honestly means "a
    lock built before this fix, or through a code path that never
    populated it," not a fabricated value, and an already-persisted
    VideoJob whose script_lock JSON predates this fix still loads
    cleanly through JsonJobStore's raw model_validate_json() with no
    migration code. ScriptLockService.build_lock() populates all
    three from the job for every *newly built* lock - the actual
    fix for the audit's complaint is there, not in the model.
    Snapshotted, not re-read from the job later, for the same reason
    quality_status is snapshotted: a later change to the job's own
    topic/duration/genre must never retroactively change what an
    already-issued lock attests to. angle stays honestly absent for
    any lock made through the older, still-live Content Production
    flow, which never selects a StoryAngle at all - only the newer,
    not-yet-wired content-intelligence pipeline does.
    """

    script_version_number: int = Field(ge=1)
    script_content_hash: str = Field(min_length=1)
    provenance: ScriptProvenance
    quality_status: ScriptQualityStatus | None = None

    topic: str | None = None
    angle: str | None = None
    target_duration_seconds: int | None = Field(default=None, gt=0)
    genre_id: str | None = None

    # Set only when locking despite unresolved blocking quality
    # findings (spec: "unless an explicitly designed override policy
    # allows it") - None means no override was needed.
    override_reason: str | None = None

    @field_validator("script_content_hash")
    @classmethod
    def clean_hash(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Script lock content hash cannot be empty.")

        return cleaned

    @field_validator("topic", "angle", "genre_id")
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None

        cleaned = value.strip()

        return cleaned or None

    @field_validator("override_reason")
    @classmethod
    def clean_override_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None

        cleaned = value.strip()

        return cleaned or None
