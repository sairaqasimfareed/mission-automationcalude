from __future__ import annotations

from enum import Enum

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel


class AudioComponentStatus(str, Enum):
    """Outcome of one component within a "Generate All Audio" run."""

    REUSED = "reused"
    GENERATED = "generated"
    FAILED = "failed"
    SKIPPED = "skipped"
    MANUAL_REQUIRED = "manual_required"


class AudioComponentResult(MissionBaseModel):
    """One component's outcome within an AudioGenerationSummary."""

    component: str
    status: AudioComponentStatus
    detail: str

    @field_validator("component", "detail")
    @classmethod
    def clean_required_text(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Audio component result text cannot be empty.")

        return cleaned


class AudioGenerationSummary(MissionBaseModel):
    """
    Result of coordinating voice/timeline/music/sound-effect
    generation as one "Generate All Audio" action - each component's
    outcome is reported individually rather than the whole action
    failing atomically on the first problem.
    """

    results: list[AudioComponentResult] = Field(default_factory=list)

    @property
    def failed_components(self) -> list[AudioComponentResult]:
        return [r for r in self.results if r.status == AudioComponentStatus.FAILED]

    @property
    def manual_required_components(self) -> list[AudioComponentResult]:
        return [
            r for r in self.results if r.status == AudioComponentStatus.MANUAL_REQUIRED
        ]

    @property
    def all_succeeded(self) -> bool:
        return not self.failed_components and not self.manual_required_components
