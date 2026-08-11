from __future__ import annotations

from enum import Enum

from pydantic import Field

from src.models.base import MissionBaseModel


class SEOValidationSeverity(str, Enum):
    """Severity level for one SEO validation issue."""

    WARNING = "warning"
    ERROR = "error"


class SEOValidationCode(str, Enum):
    """Supported SEO validation issue types."""

    NO_TITLE_CANDIDATES = "no_title_candidates"
    NO_SELECTED_TITLE = "no_selected_title"
    SELECTED_TITLE_NOT_IN_CANDIDATES = "selected_title_not_in_candidates"
    TITLE_TOO_LONG = "title_too_long"
    DUPLICATE_TITLE_CANDIDATE = "duplicate_title_candidate"

    EMPTY_DESCRIPTION = "empty_description"
    DESCRIPTION_TOO_LONG = "description_too_long"

    NO_KEYWORDS = "no_keywords"
    DUPLICATE_KEYWORD = "duplicate_keyword"

    DUPLICATE_TAG = "duplicate_tag"
    TOO_MANY_TAGS = "too_many_tags"

    DUPLICATE_HASHTAG = "duplicate_hashtag"
    TOO_MANY_HASHTAGS = "too_many_hashtags"
    INVALID_HASHTAG = "invalid_hashtag"

    LANGUAGE_MISMATCH = "language_mismatch"
    MISSING_PLATFORM_METADATA = "missing_platform_metadata"


class SEOValidationIssue(MissionBaseModel):
    """One warning or error discovered during SEO validation."""

    code: SEOValidationCode
    severity: SEOValidationSeverity

    message: str

    field: str | None = None

    metadata: dict = Field(default_factory=dict)


class SEOValidationResult(MissionBaseModel):
    """Complete validation report for one SEOPackage."""

    is_valid: bool

    errors: list[SEOValidationIssue] = Field(default_factory=list)
    warnings: list[SEOValidationIssue] = Field(default_factory=list)

    @property
    def issue_count(self) -> int:
        """Return the total number of validation issues."""

        return len(self.errors) + len(self.warnings)

    @property
    def has_warnings(self) -> bool:
        """Return whether validation produced any warnings."""

        return bool(self.warnings)
