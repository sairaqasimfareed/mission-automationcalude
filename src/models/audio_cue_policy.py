from __future__ import annotations

from enum import Enum
from uuid import UUID

from pydantic import Field

from src.models.base import MissionBaseModel


class AudioCueConflictType(str, Enum):
    """
    Post-Script-Approval Production Plan, Phase 10: "Prevent
    duplicate/repetitive SFX and uncontrolled loudness accumulation" -
    the two named policy checks this model reports on.
    """

    REPETITIVE_SFX = "repetitive_sfx"
    LOUDNESS_ACCUMULATION = "loudness_accumulation"


class AudioCueConflict(MissionBaseModel):
    """
    One actionable audio-cue policy problem - mechanically detected,
    never a claim that a track is unusable, only that it's worth a
    person's attention before render.
    """

    conflict_type: AudioCueConflictType
    track_ids: list[UUID] = Field(min_length=2)
    detail: str = Field(min_length=1)


class AudioCuePolicyResult(MissionBaseModel):
    """Result of checking one AudioTimeline's tracks for cue conflicts."""

    conflicts: list[AudioCueConflict] = Field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not self.conflicts
