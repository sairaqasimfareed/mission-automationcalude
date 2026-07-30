from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field

from src.models.base import MissionBaseModel


class VoiceTimelineValidationSeverity(str, Enum):
    """Severity of one voice timeline issue."""

    WARNING = "warning"
    ERROR = "error"


class VoiceTimelineValidationCode(str, Enum):
    """Supported voice timeline validation issue types."""

    NO_VOICE_TRACKS = "no_voice_tracks"

    DUPLICATE_SCENE_VOICE = (
        "duplicate_scene_voice"
    )

    MISSING_SCENE_NUMBER = (
        "missing_scene_number"
    )

    INVALID_SCENE_NUMBER = (
        "invalid_scene_number"
    )

    INVALID_TRACK_TYPE = "invalid_track_type"

    TRACK_NOT_READY = "track_not_ready"

    MISSING_SOURCE_FILE = "missing_source_file"

    INVALID_DURATION = "invalid_duration"

    INVALID_START_TIME = "invalid_start_time"

    VOICE_OVERLAP = "voice_overlap"

    VOICE_GAP = "voice_gap"

    MISSING_EXPECTED_SCENE = (
        "missing_expected_scene"
    )

    UNEXPECTED_SCENE = "unexpected_scene"


class VoiceTimelineValidationIssue(
    MissionBaseModel
):
    """One issue found in a voice timeline."""

    code: VoiceTimelineValidationCode

    severity: VoiceTimelineValidationSeverity

    message: str

    scene_number: int | None = None

    related_scene_number: int | None = None

    track_id: str | None = None

    start_time_seconds: float | None = None

    end_time_seconds: float | None = None

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )


class VoiceTimelineValidationResult(
    MissionBaseModel
):
    """Complete validation report for voice timeline tracks."""

    is_valid: bool

    errors: list[
        VoiceTimelineValidationIssue
    ] = Field(
        default_factory=list,
    )

    warnings: list[
        VoiceTimelineValidationIssue
    ] = Field(
        default_factory=list,
    )

    voice_track_count: int = 0

    unique_scene_count: int = 0

    total_duration_seconds: float = 0.0

    voice_duration_seconds: float = 0.0

    gap_duration_seconds: float = 0.0

    overlap_duration_seconds: float = 0.0

    missing_scene_numbers: list[int] = Field(
        default_factory=list,
    )

    unexpected_scene_numbers: list[int] = Field(
        default_factory=list,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @property
    def issue_count(self) -> int:
        """Return total validation issue count."""

        return (
            len(self.errors)
            + len(self.warnings)
        )

    @property
    def has_voice_tracks(self) -> bool:
        """Return whether voice tracks were discovered."""

        return self.voice_track_count > 0