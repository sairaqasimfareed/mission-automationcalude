from __future__ import annotations

from pydantic import Field

from src.models.base import MissionBaseModel


class VoicePitchShiftResult(MissionBaseModel):
    """
    Result of one real FFmpeg pitch-shift post-process (voice gap #3,
    2026-09-09 audit) - ElevenLabs has no pitch control at all, on any
    model, so this is applied to the already-generated audio file
    instead.
    """

    success: bool

    output_file: str | None = None

    applied_semitones: float = 0.0

    skipped: bool = False

    error_message: str | None = None

    command: list[str] = Field(default_factory=list)
