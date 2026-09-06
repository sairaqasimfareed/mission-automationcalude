from __future__ import annotations

from enum import Enum

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel
from src.models.generated_script import GeneratedScript


class ScriptIntakeMode(str, Enum):
    """
    Content Studio Redesign, Phase 15: the three named intake modes -
    how much validation an imported script goes through before it can
    become the project's canonical script.
    """

    TRUST_MY_SCRIPT = "trust_my_script"
    VALIDATE_FOR_PRODUCTION = "validate_for_production"
    FULL_QUALITY_CHECK = "full_quality_check"


class ScriptIntakeMismatch(MissionBaseModel):
    """
    One project-setting inconsistency found in an imported script -
    always reported, never silently corrected (spec: "without silently
    rewriting").
    """

    field: str = Field(min_length=1)
    expected: str = Field(min_length=1)
    detected: str = Field(min_length=1)
    note: str = Field(min_length=1)

    @field_validator("field", "expected", "detected", "note")
    @classmethod
    def clean_text(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Script intake mismatch fields cannot be empty.")

        return cleaned


class ScriptIntakeResult(MissionBaseModel):
    """
    The outcome of importing one external script - the normalized
    script plus everything a person needs to decide whether it's ready
    to proceed (spec: "Show word count, estimated narration duration
    and project-setting mismatches").
    """

    mode: ScriptIntakeMode
    script: GeneratedScript
    word_count: int = Field(ge=0)
    estimated_duration_seconds: float = Field(ge=0.0)
    target_duration_seconds: int = Field(gt=0)
    mismatches: list[ScriptIntakeMismatch] = Field(default_factory=list)

    @property
    def duration_mismatch_seconds(self) -> float:
        return abs(self.estimated_duration_seconds - self.target_duration_seconds)

    @property
    def duration_mismatch_ratio(self) -> float:
        if self.target_duration_seconds == 0:
            return 0.0

        return self.duration_mismatch_seconds / self.target_duration_seconds

    @property
    def has_significant_duration_mismatch(self) -> bool:
        """More than 20% off the project's target duration."""

        return self.duration_mismatch_ratio > 0.2
