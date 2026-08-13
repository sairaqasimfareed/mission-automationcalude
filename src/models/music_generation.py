from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, field_validator, model_validator

from src.models.audio_track import AudioTrack
from src.models.base import MissionBaseModel


class MusicGenerationStatus(str, Enum):
    """Lifecycle state of one music generation request."""

    PENDING = "pending"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


class MusicGenerationFailure(MissionBaseModel):
    """Normalized failure returned by music generation."""

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
            raise ValueError("Music generation failure text cannot be empty.")

        return cleaned


class MusicGenerationResult(MissionBaseModel):
    """Result of generating one video's background-music track."""

    success: bool

    status: MusicGenerationStatus

    provider: str | None = None

    output_file: str | None = None

    audio_track: AudioTrack | None = None

    failure: MusicGenerationFailure | None = None

    warnings: list[str] = Field(
        default_factory=list,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @model_validator(mode="after")
    def validate_result_state(self) -> MusicGenerationResult:
        if self.success:
            if self.status != MusicGenerationStatus.COMPLETED:
                raise ValueError(
                    "Successful music generation must use COMPLETED status."
                )

            if not self.output_file or self.audio_track is None:
                raise ValueError(
                    "Successful music generation requires an output file "
                    "and an audio track."
                )

            if self.failure is not None:
                raise ValueError(
                    "Successful music generation cannot contain a failure."
                )
        else:
            if self.status != MusicGenerationStatus.FAILED:
                raise ValueError("Failed music generation must use FAILED status.")

            if self.failure is None:
                raise ValueError("Failed music generation requires failure details.")

        return self
