from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, field_validator, model_validator

from src.models.base import MissionBaseModel
from src.models.voice_directives import (
    PronunciationDirective,
    VoiceDirectiveSource,
    VoiceEmotion,
    VoiceEmphasisDirective,
    VoiceEmphasisStyle,
    VoiceEnergy,
    VoicePace,
    VoicePauseDirective,
    VoicePauseStyle,
    VoicePitchStyle,
    VoiceProviderPreferences,
)


class VoiceBlueprintResolutionStatus(str, Enum):
    """Lifecycle state of one resolved voice blueprint."""

    PENDING = "pending"
    RESOLVED = "resolved"
    RESOLVED_WITH_FALLBACK = (
        "resolved_with_fallback"
    )
    GENERATED = "generated"
    FAILED = "failed"


class ResolvedVoiceProfileReference(
    MissionBaseModel
):
    """Resolved reusable voice-profile information."""

    requested_profile_id: str

    resolved_profile_id: str

    display_name: str

    profile_version: str = "1.0.0"

    found_exact_match: bool = False
    used_fallback: bool = False

    provider_mappings: dict[
        str,
        dict[str, Any],
    ] = Field(
        default_factory=dict,
    )

    warning: str | None = None

    @field_validator(
        "requested_profile_id",
        "resolved_profile_id",
    )
    @classmethod
    def validate_profile_id(
        cls,
        value: str,
    ) -> str:
        normalized = value.strip().lower()

        if (
            not normalized
            or not normalized.startswith("voice.")
            or normalized == "voice."
        ):
            raise ValueError(
                "Resolved voice profile IDs must "
                "start with 'voice.'."
            )

        return normalized

    @field_validator("display_name")
    @classmethod
    def clean_display_name(
        cls,
        value: str,
    ) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError(
                "Resolved voice profile display "
                "name cannot be empty."
            )

        return cleaned


class ResolvedVoiceBlueprint(
    MissionBaseModel
):
    """
    Final provider-independent voice generation plan.

    This model contains validated narration instructions and
    resolved profile defaults. Provider adapters may translate
    it into ElevenLabs, OpenAI, Google, Azure, or other TTS
    request formats.
    """

    schema_version: str = "1.0"

    scene_number: int = Field(
        ge=1,
    )

    status: VoiceBlueprintResolutionStatus

    profile: ResolvedVoiceProfileReference

    narration_text: str

    language: str = "English"
    language_code: str = "en"

    emotion: VoiceEmotion = VoiceEmotion.NEUTRAL
    pace: VoicePace = VoicePace.MODERATE
    energy: VoiceEnergy = VoiceEnergy.MEDIUM

    pitch_style: VoicePitchStyle = (
        VoicePitchStyle.NATURAL
    )

    pause_style: VoicePauseStyle = (
        VoicePauseStyle.NATURAL
    )

    emphasis_style: VoiceEmphasisStyle = (
        VoiceEmphasisStyle.BALANCED
    )

    speed: float = Field(
        default=1.0,
        ge=0.5,
        le=2.0,
    )

    pitch_adjustment: float = Field(
        default=0.0,
        ge=-20.0,
        le=20.0,
    )

    volume_gain_db: float = Field(
        default=0.0,
        ge=-20.0,
        le=20.0,
    )

    stability: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
    )

    similarity_boost: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
    )

    style_strength: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
    )

    speaker_boost: bool = True

    pause_before_seconds: float = Field(
        default=0.0,
        ge=0.0,
        le=30.0,
    )

    pause_after_seconds: float = Field(
        default=0.0,
        ge=0.0,
        le=30.0,
    )

    pronunciation_directives: list[
        PronunciationDirective
    ] = Field(
        default_factory=list,
    )

    pause_directives: list[
        VoicePauseDirective
    ] = Field(
        default_factory=list,
    )

    emphasis_directives: list[
        VoiceEmphasisDirective
    ] = Field(
        default_factory=list,
    )

    provider_preferences: VoiceProviderPreferences = Field(
        default_factory=VoiceProviderPreferences,
    )

    selected_provider_mapping: dict[
        str,
        Any,
    ] = Field(
        default_factory=dict,
    )

    estimated_speech_duration_seconds: float = Field(
        default=0.0,
        ge=0.0,
    )

    available_scene_duration_seconds: float | None = Field(
        default=None,
        gt=0.0,
    )

    narration_word_count: int = Field(
        default=0,
        ge=0,
    )

    narration_character_count: int = Field(
        default=0,
        ge=0,
    )

    source: VoiceDirectiveSource = (
        VoiceDirectiveSource.SYSTEM_DEFAULT
    )

    warnings: list[str] = Field(
        default_factory=list,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    output_file: str | None = None

    @field_validator(
        "narration_text",
        "language",
        "language_code",
    )
    @classmethod
    def clean_required_text(
        cls,
        value: str,
    ) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError(
                "Resolved voice blueprint text "
                "cannot be empty."
            )

        return cleaned

    @field_validator("warnings")
    @classmethod
    def clean_warnings(
        cls,
        values: list[str],
    ) -> list[str]:
        cleaned: list[str] = []

        for value in values:
            warning = value.strip()

            if warning and warning not in cleaned:
                cleaned.append(warning)

        return cleaned

    @model_validator(mode="after")
    def validate_resolution_status(
        self,
    ) -> ResolvedVoiceBlueprint:
        if (
            self.profile.used_fallback
            and self.status
            == VoiceBlueprintResolutionStatus.RESOLVED
        ):
            raise ValueError(
                "A fallback voice profile requires "
                "RESOLVED_WITH_FALLBACK status."
            )

        if (
            not self.profile.used_fallback
            and self.status
            == (
                VoiceBlueprintResolutionStatus
                .RESOLVED_WITH_FALLBACK
            )
        ):
            raise ValueError(
                "RESOLVED_WITH_FALLBACK requires "
                "a fallback profile."
            )

        if (
            self.status
            == VoiceBlueprintResolutionStatus.GENERATED
            and not self.output_file
        ):
            raise ValueError(
                "A generated voice blueprint requires "
                "an output file."
            )

        return self

    @property
    def is_resolved(self) -> bool:
        """Return whether the blueprint may be generated."""

        return self.status in {
            VoiceBlueprintResolutionStatus.RESOLVED,
            (
                VoiceBlueprintResolutionStatus
                .RESOLVED_WITH_FALLBACK
            ),
            VoiceBlueprintResolutionStatus.GENERATED,
        }

    @property
    def is_generation_ready(self) -> bool:
        """Return whether a provider may generate this voice."""

        return (
            self.status in {
                VoiceBlueprintResolutionStatus.RESOLVED,
                (
                    VoiceBlueprintResolutionStatus
                    .RESOLVED_WITH_FALLBACK
                ),
            }
            and bool(self.narration_text)
        )

    @property
    def explicit_instruction_count(self) -> int:
        """Return the number of explicit voice instructions."""

        return (
            len(self.pronunciation_directives)
            + len(self.pause_directives)
            + len(self.emphasis_directives)
        )