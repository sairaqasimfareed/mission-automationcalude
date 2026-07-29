from __future__ import annotations

from enum import Enum

from pydantic import Field

from src.models.base import MissionBaseModel


class AudioTrackType(str, Enum):
    VOICEOVER = "voiceover"
    BACKGROUND_MUSIC = "background_music"
    SOUND_EFFECT = "sound_effect"


class AudioTrackStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    MIXED = "mixed"
    FAILED = "failed"


class AudioTrack(MissionBaseModel):
    """Represents one audio asset used in the final video."""

    track_type: AudioTrackType

    source_file: str

    start_time_seconds: float = 0.0

    duration_seconds: float = 0.0

    volume: float = 1.0

    fade_in_seconds: float = 0.0

    fade_out_seconds: float = 0.0

    loop_enabled: bool = False

    duck_under_voice: bool = False

    provider: str | None = None

    license_type: str | None = None

    status: AudioTrackStatus = AudioTrackStatus.PENDING

    metadata: dict = Field(default_factory=dict)
