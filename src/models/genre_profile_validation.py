from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field

from src.models.base import MissionBaseModel


class GenreValidationSeverity(str, Enum):
    """Severity of one genre-profile validation issue."""

    WARNING = "warning"
    ERROR = "error"


class GenreValidationCode(str, Enum):
    """Supported genre-profile validation issue types."""

    UNKNOWN_EFFECT_PRESET = "unknown_effect_preset"
    EFFECT_FALLBACK_USED = "effect_fallback_used"
    INVALID_EFFECT_CATEGORY = "invalid_effect_category"
    EXCESSIVE_DEFAULT_EFFECTS = "excessive_default_effects"
    UNUSABLE_GENRE_PROFILE = "unusable_genre_profile"
    MISSING_DEFAULT_GENRE = "missing_default_genre"


class GenreValidationIssue(MissionBaseModel):
    """One issue found while validating a genre profile."""

    code: GenreValidationCode
    severity: GenreValidationSeverity

    message: str

    genre_id: str

    field_path: str | None = None

    requested_preset_id: str | None = None
    resolved_preset_id: str | None = None

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )


class ResolvedGenreEffectReference(MissionBaseModel):
    """One genre editing reference resolved through the registry."""

    field_path: str

    requested_preset_id: str

    resolved_preset_id: str | None = None

    found_exact_match: bool = False
    used_fallback: bool = False
    is_resolved: bool = False


class GenreProfileValidationResult(MissionBaseModel):
    """Complete validation report for one universal genre profile."""

    genre_id: str

    is_valid: bool
    is_production_ready: bool

    errors: list[GenreValidationIssue] = Field(
        default_factory=list,
    )

    warnings: list[GenreValidationIssue] = Field(
        default_factory=list,
    )

    resolved_effects: list[ResolvedGenreEffectReference] = Field(
        default_factory=list,
    )

    exact_match_count: int = 0
    fallback_count: int = 0
    unresolved_count: int = 0

    active_default_effect_count: int = 0

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @property
    def issue_count(self) -> int:
        """Return total validation issue count."""

        return len(self.errors) + len(self.warnings)


class GenreRegistryValidationResult(MissionBaseModel):
    """Validation report for the complete genre registry."""

    is_valid: bool

    profile_results: list[GenreProfileValidationResult] = Field(
        default_factory=list,
    )

    errors: list[GenreValidationIssue] = Field(
        default_factory=list,
    )

    warnings: list[GenreValidationIssue] = Field(
        default_factory=list,
    )

    profile_count: int = 0
    production_ready_count: int = 0

    @property
    def issue_count(self) -> int:
        """Return all registry and profile issues."""

        profile_issue_count = sum(result.issue_count for result in self.profile_results)

        return len(self.errors) + len(self.warnings) + profile_issue_count
