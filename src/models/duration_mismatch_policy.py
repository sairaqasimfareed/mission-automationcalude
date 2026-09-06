from __future__ import annotations

from enum import Enum

from pydantic import Field, model_validator

from src.models.base import MissionBaseModel


class DurationMismatchAction(str, Enum):
    """
    Post-Script-Approval Production Plan, Phase 12: "Define duration
    mismatch policy: trim, hold/freeze, approved workaround or block" -
    this codebase's own four named dispositions for a scene whose
    acquired clip doesn't match its planned duration.
    """

    TRIM = "trim"
    HOLD_LAST_FRAME = "hold_last_frame"
    APPROVED_WORKAROUND = "approved_workaround"
    BLOCK = "block"


class SceneDurationMismatch(MissionBaseModel):
    """
    One scene whose acquired clip duration disagrees with its planned
    duration by more than a configured tolerance.

    `recommended_action` is exactly that - a recommendation, not a
    final disposition. APPROVED_WORKAROUND specifically is never
    auto-assigned (see DurationMismatchPolicyService's own docstring) -
    it only ever appears here once a person has explicitly accepted a
    mismatch, at which point `note` should record who/why.
    """

    scene_number: int = Field(ge=1)
    planned_duration_seconds: float = Field(gt=0.0)
    actual_duration_seconds: float = Field(gt=0.0)
    recommended_action: DurationMismatchAction
    note: str | None = None

    @property
    def mismatch_seconds(self) -> float:
        """
        Signed difference - positive means the clip runs longer than
        planned, negative means it runs shorter.
        """

        return self.actual_duration_seconds - self.planned_duration_seconds

    @model_validator(mode="after")
    def validate_approved_workaround_has_a_note(self) -> SceneDurationMismatch:
        if self.recommended_action == DurationMismatchAction.APPROVED_WORKAROUND and (
            not self.note or not self.note.strip()
        ):
            raise ValueError("An approved workaround must record who/why approved it.")

        return self
