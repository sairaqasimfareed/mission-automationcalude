from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, field_validator, model_validator

from src.models.audio_track import AudioTrack
from src.models.base import MissionBaseModel


class SoundEffectGenerationStatus(str, Enum):
    """Lifecycle state of one sound-effect generation request."""

    PENDING = "pending"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


class SoundEffectGenerationFailure(MissionBaseModel):
    """Normalized failure returned by sound-effect generation."""

    reason: str

    message: str

    provider: str | None = None

    @field_validator("reason", "message")
    @classmethod
    def clean_required_text(
        cls,
        value: str,
    ) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Sound-effect generation failure text cannot be empty.")

        return cleaned


class SoundEffectGenerationResult(MissionBaseModel):
    """Result of generating one scene sound-effect cue."""

    success: bool

    scene_number: int = Field(
        ge=1,
    )

    status: SoundEffectGenerationStatus

    provider: str | None = None

    output_file: str | None = None

    audio_track: AudioTrack | None = None

    failure: SoundEffectGenerationFailure | None = None

    warnings: list[str] = Field(
        default_factory=list,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @model_validator(mode="after")
    def validate_result_state(self) -> SoundEffectGenerationResult:
        if self.success:
            if self.status != SoundEffectGenerationStatus.COMPLETED:
                raise ValueError(
                    "Successful sound-effect generation must use " "COMPLETED status."
                )

            if not self.output_file or self.audio_track is None:
                raise ValueError(
                    "Successful sound-effect generation requires an "
                    "output file and an audio track."
                )

            if self.failure is not None:
                raise ValueError(
                    "Successful sound-effect generation cannot contain " "a failure."
                )
        else:
            if self.status != SoundEffectGenerationStatus.FAILED:
                raise ValueError(
                    "Failed sound-effect generation must use FAILED status."
                )

            if self.failure is None:
                raise ValueError(
                    "Failed sound-effect generation requires failure details."
                )

        return self
