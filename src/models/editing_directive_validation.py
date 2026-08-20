from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field

from src.models.base import MissionBaseModel


class DirectiveValidationSeverity(str, Enum):
    """Severity of one editing-directive validation issue."""

    WARNING = "warning"
    ERROR = "error"


class DirectiveValidationCode(str, Enum):
    """Supported editing-directive validation issue types."""

    UNKNOWN_PRESET = "unknown_preset"
    FALLBACK_USED = "fallback_used"
    DIRECTIVE_OUTSIDE_SCENE = "directive_outside_scene"
    INVALID_SCENE_DURATION = "invalid_scene_duration"
    TRANSITIONS_EXCEED_SCENE = "transitions_exceed_scene"
    MUSIC_FADES_EXCEED_SCENE = "music_fades_exceed_scene"
    EXCESSIVE_EFFECT_COUNT = "excessive_effect_count"


class DirectiveValidationIssue(MissionBaseModel):
    """One issue found while validating editing directives."""

    code: DirectiveValidationCode
    severity: DirectiveValidationSeverity

    message: str

    directive_path: str | None = None
    requested_preset_id: str | None = None
    resolved_preset_id: str | None = None

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )


class ResolvedDirectiveReference(MissionBaseModel):
    """One directive ID resolved through the effect registry."""

    directive_path: str

    requested_preset_id: str
    resolved_preset_id: str | None = None

    found_exact_match: bool = False
    used_fallback: bool = False
    is_resolved: bool = False


class EditingDirectiveValidationResult(MissionBaseModel):
    """Complete validation result for one scene blueprint."""

    scene_number: int

    is_valid: bool
    is_render_ready: bool

    errors: list[DirectiveValidationIssue] = Field(
        default_factory=list,
    )

    warnings: list[DirectiveValidationIssue] = Field(
        default_factory=list,
    )

    resolved_directives: list[ResolvedDirectiveReference] = Field(
        default_factory=list,
    )

    exact_match_count: int = 0
    fallback_count: int = 0
    unresolved_count: int = 0

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @property
    def issue_count(self) -> int:
        """Return the total number of issues."""

        return len(self.errors) + len(self.warnings)
