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
    """

    script_version_number: int = Field(ge=1)
    script_content_hash: str = Field(min_length=1)
    provenance: ScriptProvenance
    quality_status: ScriptQualityStatus | None = None

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

    @field_validator("override_reason")
    @classmethod
    def clean_override_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None

        cleaned = value.strip()

        return cleaned or None
