from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from pydantic import Field

from src.models.base import MissionBaseModel


class ClipVerificationSeverity(str, Enum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


class ClipVerificationIssueCode(str, Enum):
    NO_CLIP = "no_clip"
    FILE_MISSING = "file_missing"
    UNREADABLE = "unreadable"
    NO_VIDEO_STREAM = "no_video_stream"
    DUPLICATE_CONTENT = "duplicate_content"
    TOO_SHORT = "too_short"
    TOO_LONG = "too_long"
    LAST_ATTEMPT_FAILED = "last_attempt_failed"


class ClipVerificationIssue(MissionBaseModel):
    code: ClipVerificationIssueCode
    severity: ClipVerificationSeverity
    message: str


class SceneClipVerification(MissionBaseModel):
    """What was found for one scene's attached clip(s)."""

    scene_number: int
    scene_title: str = ""
    narration: str = ""

    # What the scene needs (real narration length once known, else the plan).
    expected_seconds: float | None = None
    # What is actually attached (sum over the scene's sub-clips, from ffprobe).
    actual_seconds: float | None = None

    clip_files: list[str] = Field(default_factory=list)
    provider: str | None = None

    # A still from the attached clip, so the operator can see at a glance
    # whether the picture matches the narration. A derived cache file, never
    # state - regenerated on every verification.
    thumbnail_file: str | None = None

    issues: list[ClipVerificationIssue] = Field(default_factory=list)

    @property
    def severity(self) -> ClipVerificationSeverity:
        severities = {issue.severity for issue in self.issues}

        if ClipVerificationSeverity.ERROR in severities:
            return ClipVerificationSeverity.ERROR

        if ClipVerificationSeverity.WARNING in severities:
            return ClipVerificationSeverity.WARNING

        return ClipVerificationSeverity.OK


class ClipAttachmentVerificationReport(MissionBaseModel):
    """
    The result of checking that every scene has the right clip attached.

    Derived entirely from the job (its clips and its generation ledgers) and
    recomputable at any time - stored on VideoJob only so that a run left
    unattended still has its verdict waiting when the operator returns,
    including after an app restart. `clip_signature` records exactly which
    clips were checked, so a report that no longer matches the job's current
    clips can be shown as out of date rather than trusted.
    """

    verified_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    clip_signature: str = ""
    scenes: list[SceneClipVerification] = Field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(
            1
            for scene in self.scenes
            if scene.severity == ClipVerificationSeverity.ERROR
        )

    @property
    def warning_count(self) -> int:
        return sum(
            1
            for scene in self.scenes
            if scene.severity == ClipVerificationSeverity.WARNING
        )

    @property
    def ok_count(self) -> int:
        return sum(
            1 for scene in self.scenes if scene.severity == ClipVerificationSeverity.OK
        )

    @property
    def is_clean(self) -> bool:
        return bool(self.scenes) and self.error_count == 0 and self.warning_count == 0
