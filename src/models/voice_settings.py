from __future__ import annotations

from pydantic import Field, model_validator

from src.models.base import MissionBaseModel
from src.models.specification_enums import (
    NarrationStyle,
    SubtitleMode,
    VoiceGender,
    VoiceStrategy,
)


class VoiceSettings(MissionBaseModel):
    """Defines project-level voiceover production preferences."""

    schema_version: str = "1.0"

    strategy: VoiceStrategy = VoiceStrategy.MANUAL_UPLOAD

    language: str = Field(
        default="English",
        min_length=2,
        max_length=100,
    )

    preferred_gender: VoiceGender = VoiceGender.NEUTRAL

    narration_style: NarrationStyle = (
        NarrationStyle.NATURAL
    )

    speaking_rate: float = Field(
        default=1.0,
        ge=0.5,
        le=2.0,
    )

    pitch: float = Field(
        default=0.0,
        ge=-20.0,
        le=20.0,
    )

    volume_gain_db: float = Field(
        default=0.0,
        ge=-20.0,
        le=20.0,
    )

    subtitle_mode: SubtitleMode = (
        SubtitleMode.AUTO_GENERATE
    )

    preferred_provider_profile_id: str | None = None
    preferred_model: str | None = None
    preferred_voice_id: str | None = None

    manual_voice_file: str | None = None

    normalize_audio: bool = True
    remove_silence: bool = False

    @model_validator(mode="after")
    def validate_voice_settings(self) -> "VoiceSettings":
        """Prevent contradictory voice configuration states."""

        self.language = self.language.strip()

        if not self.language:
            raise ValueError(
                "Voice language cannot be empty."
            )

        if self.strategy == VoiceStrategy.MANUAL_UPLOAD:
            if self.preferred_provider_profile_id is not None:
                raise ValueError(
                    "Manual voice strategy cannot use an "
                    "automatic voice provider profile."
                )

            if self.preferred_model is not None:
                raise ValueError(
                    "Manual voice strategy cannot define "
                    "an automatic voice model."
                )

            if self.preferred_voice_id is not None:
                raise ValueError(
                    "Manual voice strategy cannot define "
                    "an automatic voice ID."
                )

        if self.strategy == VoiceStrategy.AUTO_GENERATE:
            if self.manual_voice_file is not None:
                raise ValueError(
                    "Automatic voice strategy cannot include "
                    "a manual voice file."
                )

        if (
            self.subtitle_mode == SubtitleMode.MANUAL_UPLOAD
            and self.strategy == VoiceStrategy.AUTO_GENERATE
        ):
            # Allowed: generated voice with manually supplied subtitles.
            pass

        return self