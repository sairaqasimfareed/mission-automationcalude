from __future__ import annotations

from enum import Enum

from pydantic import Field

from src.models.base import MissionBaseModel


class ThumbnailValidationSeverity(str, Enum):
    """Severity level for one thumbnail validation issue."""

    WARNING = "warning"
    ERROR = "error"


class ThumbnailValidationCode(str, Enum):
    """Supported thumbnail validation issue types."""

    FILE_MISSING = "file_missing"
    INVALID_DIMENSIONS = "invalid_dimensions"
    UNSUPPORTED_ASPECT_RATIO = "unsupported_aspect_ratio"
    HOOK_TEXT_TOO_LONG = "hook_text_too_long"
    HOOK_TEXT_OUTSIDE_SAFE_MARGIN = "hook_text_outside_safe_margin"
    NO_CONCEPT_SELECTED = "no_concept_selected"


class ThumbnailValidationIssue(MissionBaseModel):
    """One warning or error discovered during thumbnail validation."""

    code: ThumbnailValidationCode
    severity: ThumbnailValidationSeverity

    message: str

    field: str | None = None

    metadata: dict = Field(default_factory=dict)


class ThumbnailValidationResult(MissionBaseModel):
    """Complete validation report for one ThumbnailArtifact."""

    is_valid: bool

    errors: list[ThumbnailValidationIssue] = Field(default_factory=list)
    warnings: list[ThumbnailValidationIssue] = Field(default_factory=list)

    @property
    def issue_count(self) -> int:
        """Return the total number of validation issues."""

        return len(self.errors) + len(self.warnings)

    @property
    def has_warnings(self) -> bool:
        """Return whether validation produced any warnings."""

        return bool(self.warnings)
