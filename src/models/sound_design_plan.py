from __future__ import annotations

from enum import Enum

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel
from src.models.editing_directives import (
    DirectiveIntensity,
    DirectiveTimingMode,
)

# Real ElevenLabs pay-as-you-go API rates, confirmed 2026-09-13:
# sound effects $0.0194/effect flat, music $0.64 per STARTED minute
# (any partial minute bills as a full minute - so cost estimation
# must round up, not just multiply by exact seconds).
SOUND_EFFECT_COST_PER_CUE_USD = 0.0194
MUSIC_COST_PER_STARTED_MINUTE_USD = 0.64


class SoundDesignItemStatus(str, Enum):
    """Generation lifecycle of one planned sound-design item."""

    PENDING = "pending"
    GENERATED = "generated"
    FAILED = "failed"


class SoundEffectCueDirective(MissionBaseModel):
    """
    One content-aware sound-effect cue proposed for a specific scene.

    Unlike a genre-level SoundEffectDirective (the same fixed preset
    applied identically to every scene), this cue is generated from
    that scene's own narration - generation_prompt is written from
    the actual content ("three slow deliberate wooden knocks from
    directly above"), not looked up from a small fixed preset list.
    preset_id is set only when an existing registered EffectPreset is
    a genuinely close match (reuse it - cheaper, already QA'd);
    otherwise it stays None and generation_prompt drives a fresh,
    bespoke ElevenLabs sound-generation call.
    """

    scene_number: int = Field(ge=1)

    generation_prompt: str = Field(min_length=1, max_length=500)

    preset_id: str | None = None

    timing_mode: DirectiveTimingMode = DirectiveTimingMode.ABSOLUTE_SECONDS

    start_offset_seconds: float = Field(default=0.0, ge=0.0)
    relative_position_percent: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
    )

    volume_percent: float = Field(default=70.0, ge=0.0, le=100.0)

    intensity: DirectiveIntensity = DirectiveIntensity.MEDIUM

    # Why this cue exists - the specific narration phrase that
    # motivated it. Kept even after generation so a reviewer can judge
    # whether an edited/regenerated prompt still fits.
    rationale: str = Field(min_length=1, max_length=400)

    status: SoundDesignItemStatus = SoundDesignItemStatus.PENDING

    audio_track_id: str | None = None

    @field_validator("generation_prompt", "rationale")
    @classmethod
    def clean_text(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Sound-effect cue text cannot be empty.")

        return cleaned

    @property
    def estimated_cost_usd(self) -> float:
        return SOUND_EFFECT_COST_PER_CUE_USD


class MusicMoodSegment(MissionBaseModel):
    """
    One content-aware background-music mood segment spanning a scene
    range, replacing a single static genre-wide music track for the
    whole video with a plan that can actually shift mood/intensity as
    the story does.
    """

    start_scene_number: int = Field(ge=1)
    end_scene_number: int = Field(ge=1)

    mood_description: str = Field(min_length=1, max_length=400)

    intensity: DirectiveIntensity = DirectiveIntensity.MEDIUM

    rationale: str = Field(min_length=1, max_length=400)

    status: SoundDesignItemStatus = SoundDesignItemStatus.PENDING

    audio_track_id: str | None = None

    @field_validator("mood_description", "rationale")
    @classmethod
    def clean_text(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Music mood segment text cannot be empty.")

        return cleaned

    @field_validator("end_scene_number")
    @classmethod
    def validate_scene_range(cls, value: int, info) -> int:
        start = info.data.get("start_scene_number")

        if start is not None and value < start:
            raise ValueError(
                "Music mood segment end_scene_number cannot be "
                "before start_scene_number."
            )

        return value

    def estimated_cost_usd(
        self,
        *,
        segment_duration_seconds: float,
    ) -> float:
        """
        ElevenLabs bills music per STARTED minute - any partial
        minute rounds up to a full minute, so this must round up too,
        not multiply by exact fractional minutes.
        """

        if segment_duration_seconds <= 0.0:
            return 0.0

        started_minutes = -(-int(segment_duration_seconds) // 60)  # ceil div

        return started_minutes * MUSIC_COST_PER_STARTED_MINUTE_USD


class SoundDesignPlan(MissionBaseModel):
    """
    Content-aware sound-design plan for one video: scene-specific SFX
    cues plus a music mood curve, generated from the actual script
    rather than a fixed genre-wide preset list. Optional on VideoJob -
    absent means the render pipeline falls back to today's genre-level
    SoundEffectDirective/MusicDirective behavior unchanged.
    """

    sfx_cues: list[SoundEffectCueDirective] = Field(default_factory=list)

    music_segments: list[MusicMoodSegment] = Field(default_factory=list)

    provider: str | None = None
    model: str | None = None
    estimated_generation_cost_usd: float = Field(default=0.0, ge=0.0)

    warnings: list[str] = Field(default_factory=list)
