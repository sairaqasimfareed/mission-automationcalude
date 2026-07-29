from __future__ import annotations

from pydantic import Field

from src.models.audio_track import AudioTrack
from src.models.base import MissionBaseModel


class AudioTimeline(MissionBaseModel):
    """
    Complete audio timeline for a video.

    Contains:

    - Voiceover
    - Background Music
    - Sound Effects
    """

    tracks: list[AudioTrack] = Field(default_factory=list)

    total_duration_seconds: float = 0.0

    sample_rate: int = 48000

    channels: int = 2

    output_file: str | None = None

    def calculate_duration(self) -> float:

        if not self.tracks:
            self.total_duration_seconds = 0.0
            return self.total_duration_seconds

        self.total_duration_seconds = max(
            track.start_time_seconds + track.duration_seconds for track in self.tracks
        )

        return self.total_duration_seconds
