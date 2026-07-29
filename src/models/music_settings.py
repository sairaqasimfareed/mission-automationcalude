from __future__ import annotations

from pydantic import Field, model_validator

from src.models.base import MissionBaseModel
from src.models.specification_enums import (
    MusicMood,
    MusicStrategy,
)


class MusicSettings(MissionBaseModel):
    """Project-level background music configuration."""

    schema_version: str = "1.0"

    strategy: MusicStrategy = MusicStrategy.AUTO_GENERATE

    mood: MusicMood = MusicMood.CINEMATIC

    volume: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
    )

    fade_in_seconds: float = Field(
        default=1.0,
        ge=0.0,
        le=30.0,
    )

    fade_out_seconds: float = Field(
        default=1.0,
        ge=0.0,
        le=30.0,
    )

    loop_music: bool = True

    preferred_provider_profile_id: str | None = None

    preferred_model: str | None = None

    manual_music_file: str | None = None

    normalize_audio: bool = True

    duck_under_voice: bool = True

    @model_validator(mode="after")
    def validate_music_settings(self) -> MusicSettings:

        if (
            self.strategy == MusicStrategy.MANUAL_UPLOAD
            and self.preferred_provider_profile_id is not None
        ):
            raise ValueError("Manual music cannot use an automatic provider.")

        if (
            self.strategy == MusicStrategy.AUTO_GENERATE
            and self.manual_music_file is not None
        ):
            raise ValueError(
                "Automatic music generation cannot include " "a manual music file."
            )

        if self.strategy == MusicStrategy.NONE and self.volume != 0.0:
            raise ValueError("Music strategy NONE requires volume to be 0.")

        return self
