from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field

from src.models.base import MissionBaseModel


class VoiceValidationSeverity(str, Enum):
    """Severity of one voice-directive validation issue."""

    WARNING = "warning"
    ERROR = "error"


class VoiceValidationCode(str, Enum):
    """Supported voice-directive validation issue types."""

    EMPTY_NARRATION = "empty_narration"
    VOICE_PROFILE_FALLBACK_USED = (
        "voice_profile_fallback_used"
    )
    UNRESOLVED_VOICE_PROFILE = (
        "unresolved_voice_profile"
    )
    PAUSE_TEXT_NOT_FOUND = "pause_text_not_found"
    PAUSE_INDEX_OUT_OF_RANGE = (
        "pause_index_out_of_range"
    )
    EMPHASIS_TEXT_NOT_FOUND = (
        "emphasis_text_not_found"
    )
    EMPHASIS_OCCURRENCE_NOT_FOUND = (
        "emphasis_occurrence_not_found"
    )
    PRONUNCIATION_TEXT_NOT_FOUND = (
        "pronunciation_text_not_found"
    )
    LANGUAGE_MISMATCH = "language_mismatch"
    INVALID_SCENE_DURATION = (
        "invalid_scene_duration"
    )
    SPEECH_EXCEEDS_SCENE = "speech_exceeds_scene"
    EXCESSIVE_SPEECH_GAP = "excessive_speech_gap"
    EXCESSIVE_EXPLICIT_INSTRUCTIONS = (
        "excessive_explicit_instructions"
    )


class VoiceValidationIssue(MissionBaseModel):
    """One issue found while validating voice directives."""

    code: VoiceValidationCode
    severity: VoiceValidationSeverity

    message: str

    scene_number: int

    directive_path: str | None = None

    requested_profile_id: str | None = None
    resolved_profile_id: str | None = None

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )


class VoiceProfileValidationReference(
    MissionBaseModel
):
    """Voice-profile resolution details for validation."""

    requested_profile_id: str

    resolved_profile_id: str | None = None

    found_exact_match: bool = False
    used_fallback: bool = False
    is_resolved: bool = False


class VoiceDirectiveValidationResult(
    MissionBaseModel
):
    """Complete validation report for one scene voice request."""

    scene_number: int

    is_valid: bool
    is_generation_ready: bool

    profile_reference: (
        VoiceProfileValidationReference | None
    ) = None

    errors: list[
        VoiceValidationIssue
    ] = Field(
        default_factory=list,
    )

    warnings: list[
        VoiceValidationIssue
    ] = Field(
        default_factory=list,
    )

    narration_character_count: int = 0
    narration_word_count: int = 0

    estimated_speech_duration_seconds: float = 0.0

    available_scene_duration_seconds: float | None = None

    explicit_instruction_count: int = 0

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @property
    def issue_count(self) -> int:
        """Return total validation issue count."""

        return len(self.errors) + len(self.warnings)