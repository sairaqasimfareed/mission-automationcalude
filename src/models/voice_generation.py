from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, field_validator, model_validator

from src.models.audio_track import AudioTrack
from src.models.base import MissionBaseModel
from src.models.resolved_voice_blueprint import (
    ResolvedVoiceBlueprint,
)


class VoiceGenerationStatus(str, Enum):
    """Lifecycle state of one voice generation request."""

    PENDING = "pending"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


class VoiceGenerationFailureReason(str, Enum):
    """Normalized reasons for voice generation failure."""

    NO_PROVIDER_AVAILABLE = "no_provider_available"
    PROVIDER_UNHEALTHY = "provider_unhealthy"
    BLUEPRINT_NOT_READY = "blueprint_not_ready"
    PROVIDER_ERROR = "provider_error"
    EMPTY_OUTPUT_PATH = "empty_output_path"
    UNSUPPORTED_OUTPUT_FORMAT = "unsupported_output_format"


class VoiceGenerationFailure(MissionBaseModel):
    """Normalized failure returned by voice generation."""

    reason: VoiceGenerationFailureReason

    message: str

    provider: str | None = None

    recoverable: bool = True

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator("message")
    @classmethod
    def clean_message(
        cls,
        value: str,
    ) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Voice generation failure message " "cannot be empty.")

        return cleaned


class VoiceGenerationJob(MissionBaseModel):
    """One provider-independent voice generation job."""

    scene_number: int = Field(
        ge=1,
    )

    blueprint: ResolvedVoiceBlueprint

    status: VoiceGenerationStatus = VoiceGenerationStatus.PENDING

    selected_provider: str | None = None

    attempts: int = Field(
        default=0,
        ge=0,
    )

    output_file: str | None = None

    failure: VoiceGenerationFailure | None = None

    warnings: list[str] = Field(
        default_factory=list,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @model_validator(mode="after")
    def validate_scene_number(
        self,
    ) -> VoiceGenerationJob:
        if self.scene_number != self.blueprint.scene_number:
            raise ValueError(
                "Voice generation job scene number " "must match its blueprint."
            )

        return self


class VoiceGenerationResult(MissionBaseModel):
    """Result of generating one scene voiceover."""

    success: bool

    scene_number: int = Field(
        ge=1,
    )

    status: VoiceGenerationStatus

    provider: str | None = None

    output_file: str | None = None

    audio_track: AudioTrack | None = None

    attempts: int = Field(
        default=0,
        ge=0,
    )

    failure: VoiceGenerationFailure | None = None

    warnings: list[str] = Field(
        default_factory=list,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @model_validator(mode="after")
    def validate_result_state(
        self,
    ) -> VoiceGenerationResult:
        if self.success:
            if self.status != VoiceGenerationStatus.COMPLETED:
                raise ValueError(
                    "Successful voice generation must " "use COMPLETED status."
                )

            if not self.output_file:
                raise ValueError(
                    "Successful voice generation requires " "an output file."
                )

            if self.audio_track is None:
                raise ValueError(
                    "Successful voice generation requires " "an audio track."
                )

            if self.failure is not None:
                raise ValueError(
                    "Successful voice generation cannot " "contain a failure."
                )

        else:
            if self.status != VoiceGenerationStatus.FAILED:
                raise ValueError("Failed voice generation must use " "FAILED status.")

            if self.failure is None:
                raise ValueError("Failed voice generation requires " "failure details.")

        return self
