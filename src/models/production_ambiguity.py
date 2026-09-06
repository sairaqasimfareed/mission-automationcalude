from __future__ import annotations

from enum import Enum

from pydantic import Field, field_validator, model_validator

from src.models.base import MissionBaseModel


class AmbiguityResolutionStatus(str, Enum):
    """
    Content Studio Redesign, Phase 16: "Unknown continuity-critical
    choices become ambiguities rather than silent permanent
    inventions." How one production ambiguity currently stands.
    """

    UNRESOLVED = "unresolved"
    RESOLVED_MANUALLY = "resolved_manually"
    RESOLVED_BY_AI = "resolved_by_ai"


class ProductionAmbiguity(MissionBaseModel):
    """
    One production-relevant question the script's text does not
    settle - e.g. an unclear time period, an undescribed character's
    appearance, or a segment with no usable visual direction. Never
    silently invented; always surfaced for a person (or an explicit
    "Let AI Decide" action) to resolve.
    """

    description: str = Field(min_length=1)
    segment_number: int | None = Field(default=None, ge=1)

    # "continuity-critical" ambiguities are the ones spec's exit
    # criterion cares about ("unresolved blocking ambiguities prevent
    # lock or production only when genuinely required") - a merely
    # cosmetic ambiguity (e.g. "could use more B-roll variety here")
    # is worth surfacing but should never block anything.
    continuity_critical: bool = False

    status: AmbiguityResolutionStatus = AmbiguityResolutionStatus.UNRESOLVED
    resolution_note: str | None = None

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Production ambiguity description cannot be empty.")

        return cleaned

    @field_validator("resolution_note")
    @classmethod
    def clean_resolution_note(cls, value: str | None) -> str | None:
        if value is None:
            return None

        cleaned = value.strip()

        return cleaned or None

    @model_validator(mode="after")
    def validate_resolution_consistency(self) -> ProductionAmbiguity:
        if (
            self.status != AmbiguityResolutionStatus.UNRESOLVED
            and not self.resolution_note
        ):
            raise ValueError(
                "A resolved ambiguity requires a resolution_note explaining "
                "the resolution."
            )

        return self

    @property
    def is_blocking(self) -> bool:
        return (
            self.continuity_critical
            and self.status == AmbiguityResolutionStatus.UNRESOLVED
        )
