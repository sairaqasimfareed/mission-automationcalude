from __future__ import annotations

from enum import Enum
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from src.models.base import MissionBaseModel
from src.models.editorial_critique import CriticFinding


class ScriptQualityStatus(str, Enum):
    """
    Editorial lifecycle status of one generated script.

    DRAFT is the implicit pre-evaluation state (no ScriptQualityReport
    exists yet for the script) - ScriptQualityGateService.evaluate()
    never returns it, only the three post-evaluation outcomes below.
    """

    DRAFT = "draft"
    NEEDS_REVISION = "needs_revision"
    EDITORIAL_REVIEW = "editorial_review"
    APPROVED_FOR_PRODUCTION = "approved_for_production"


class FindingResolutionAction(str, Enum):
    """What a person did about one critic finding, for the audit trail
    Phase 13 asks for ("Store ignored findings with user reason")."""

    APPLIED = "applied"
    IGNORED = "ignored"


class FindingResolution(MissionBaseModel):
    """
    A record of what happened to one CriticFinding from a specific
    ScriptQualityReport - never mutates the finding itself (findings
    are immutable evidence of what the critique found), just tracks
    the disposition alongside it.
    """

    finding_id: UUID
    action: FindingResolutionAction
    reason: str | None = None

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None

        cleaned = value.strip()

        return cleaned or None

    @model_validator(mode="after")
    def validate_reason_required_for_ignore(self) -> FindingResolution:
        if self.action == FindingResolutionAction.IGNORED and not self.reason:
            raise ValueError("Ignoring a finding requires a non-empty reason.")

        return self


class ScriptQualityReport(MissionBaseModel):
    """
    Aggregation of one EditorialCritique against its genre's quality
    thresholds (spec: quality gates, not vibes). Pure aggregation -
    every score and finding here was produced upstream by the
    critique pass; this model and its producing service never invent
    a score of their own.
    """

    topic: str = Field(min_length=1)
    genre_id: str = Field(min_length=1)

    dimension_scores: dict[str, int] = Field(default_factory=dict)
    dimension_thresholds: dict[str, int] = Field(default_factory=dict)
    failed_dimensions: list[str] = Field(default_factory=list)

    blocking_findings: list[CriticFinding] = Field(default_factory=list)
    major_findings: list[CriticFinding] = Field(default_factory=list)

    status: ScriptQualityStatus

    # Content Studio Redesign, Phase 13: "Quality result binds to
    # exact Script version/hash" - both optional so a report produced
    # without a version_history (or in an existing test that predates
    # this phase) still constructs exactly as before; the real
    # pipeline call site always supplies both going forward.
    script_version_number: int | None = Field(default=None, ge=1)
    script_content_hash: str | None = None

    # Phase 13: "Store ignored findings with user reason." Append-only,
    # like every other audit trail in this codebase.
    resolutions: list[FindingResolution] = Field(default_factory=list)

    @field_validator("genre_id")
    @classmethod
    def validate_genre_id(cls, value: str) -> str:
        normalized = value.strip().lower()

        if not normalized.startswith("genre."):
            raise ValueError("Genre ID must start with 'genre.'.")

        return normalized

    @property
    def passed(self) -> bool:
        """Return whether this script is approved for production."""

        return self.status == ScriptQualityStatus.APPROVED_FOR_PRODUCTION

    @property
    def all_findings(self) -> list[CriticFinding]:
        """Every finding this report carries, blocking and major alike."""

        return [*self.blocking_findings, *self.major_findings]

    def resolution_for(self, finding_id: UUID) -> FindingResolution | None:
        return next((r for r in self.resolutions if r.finding_id == finding_id), None)

    @property
    def unresolved_blocking_findings(self) -> list[CriticFinding]:
        """
        Blocking findings nobody has explicitly applied or ignored yet
        - Phase 14's Script Lock exit criterion ("No Script Lock when
        unresolved blocking issues exist") reads this directly.
        """

        return [
            finding
            for finding in self.blocking_findings
            if self.resolution_for(finding.id) is None
        ]
