from __future__ import annotations

from enum import Enum

from pydantic import Field

from src.models.base import MissionBaseModel


class FinalExportValidationSeverity(str, Enum):
    """Severity level for one final export validation issue."""

    WARNING = "warning"
    ERROR = "error"


class FinalExportValidationCode(str, Enum):
    """Supported final export validation issue types."""

    VIDEO_FILE_MISSING = "video_file_missing"
    THUMBNAIL_NOT_READY = "thumbnail_not_ready"
    SEO_PACKAGE_NOT_READY = "seo_package_not_ready"
    INVALID_DURATION = "invalid_duration"
    MANIFEST_MISSING = "manifest_missing"


class FinalExportValidationIssue(MissionBaseModel):
    """One warning or error discovered during final export validation."""

    code: FinalExportValidationCode
    severity: FinalExportValidationSeverity

    message: str

    field: str | None = None

    metadata: dict = Field(default_factory=dict)


class FinalExportValidationResult(MissionBaseModel):
    """Complete validation report for one FinalExportPackage."""

    is_valid: bool

    errors: list[FinalExportValidationIssue] = Field(default_factory=list)
    warnings: list[FinalExportValidationIssue] = Field(default_factory=list)

    @property
    def issue_count(self) -> int:
        """Return the total number of validation issues."""

        return len(self.errors) + len(self.warnings)

    @property
    def has_warnings(self) -> bool:
        """Return whether validation produced any warnings."""

        return bool(self.warnings)
