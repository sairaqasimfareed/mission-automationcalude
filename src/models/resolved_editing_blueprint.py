from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field

from src.models.base import MissionBaseModel
from src.models.editing_directives import (
    DirectiveIntensity,
    DirectiveTimingMode,
)


class BlueprintResolutionStatus(str, Enum):
    """Lifecycle state of a resolved editing blueprint."""

    RESOLVED = "resolved"
    RESOLVED_WITH_FALLBACKS = "resolved_with_fallbacks"
    FAILED = "failed"
    APPLIED = "applied"


class ResolvedPresetReference(MissionBaseModel):
    """One effect preset resolved from the registry."""

    directive_path: str

    requested_preset_id: str
    resolved_preset_id: str

    found_exact_match: bool = False
    used_fallback: bool = False

    implementation: dict[str, Any] = Field(
        default_factory=dict,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )


class ResolvedCameraInstruction(MissionBaseModel):
    """Resolved camera instruction for one scene."""

    preset: ResolvedPresetReference

    intensity: DirectiveIntensity = DirectiveIntensity.MEDIUM

    start_offset_seconds: float = 0.0
    end_offset_seconds: float | None = None

    zoom_start: float | None = None
    zoom_end: float | None = None


class ResolvedTransitionInstruction(MissionBaseModel):
    """Resolved transition instruction."""

    preset: ResolvedPresetReference

    duration_seconds: float = 0.0

    intensity: DirectiveIntensity = DirectiveIntensity.MEDIUM


class ResolvedVisualEffectInstruction(MissionBaseModel):
    """Resolved visual-effect instruction."""

    preset: ResolvedPresetReference

    intensity: DirectiveIntensity = DirectiveIntensity.MEDIUM

    timing_mode: DirectiveTimingMode = DirectiveTimingMode.FULL_SCENE

    start_offset_seconds: float = 0.0
    duration_seconds: float | None = None

    relative_position_percent: float | None = None

    enabled: bool = True


class ResolvedAnimationInstruction(MissionBaseModel):
    """Resolved animation instruction."""

    preset: ResolvedPresetReference

    intensity: DirectiveIntensity = DirectiveIntensity.MEDIUM

    start_offset_seconds: float = 0.0
    duration_seconds: float | None = None

    enabled: bool = True


class ResolvedMusicInstruction(MissionBaseModel):
    """Resolved background-music instruction."""

    preset: ResolvedPresetReference

    intensity: DirectiveIntensity = DirectiveIntensity.LOW

    volume_percent: float = 25.0

    fade_in_seconds: float = 0.0
    fade_out_seconds: float = 0.0

    duck_under_voice: bool = True
    enabled: bool = True


class ResolvedSoundEffectInstruction(MissionBaseModel):
    """Resolved sound-effect instruction."""

    preset: ResolvedPresetReference

    timing_mode: DirectiveTimingMode = DirectiveTimingMode.ABSOLUTE_SECONDS

    start_offset_seconds: float = 0.0
    relative_position_percent: float | None = None

    volume_percent: float = 70.0

    intensity: DirectiveIntensity = DirectiveIntensity.MEDIUM

    enabled: bool = True


class ResolvedSubtitleInstruction(MissionBaseModel):
    """Resolved subtitle styling instruction."""

    preset: ResolvedPresetReference

    animation_preset: ResolvedPresetReference | None = None

    enabled: bool = True
    burn_into_video: bool = True

    maximum_words_per_line: int = 8


class ResolvedSceneEditingBlueprint(MissionBaseModel):
    """
    Complete provider-independent editing blueprint.

    All preset IDs have already been resolved through the
    effect registry. Renderer-specific command generation
    happens in a later service.
    """

    schema_version: str = "1.0"

    scene_number: int

    genre_preset: ResolvedPresetReference

    camera: ResolvedCameraInstruction

    transition_in: ResolvedTransitionInstruction
    transition_out: ResolvedTransitionInstruction

    visual_effects: list[ResolvedVisualEffectInstruction] = Field(
        default_factory=list,
    )

    animations: list[ResolvedAnimationInstruction] = Field(
        default_factory=list,
    )

    music: ResolvedMusicInstruction

    sound_effects: list[ResolvedSoundEffectInstruction] = Field(
        default_factory=list,
    )

    subtitles: ResolvedSubtitleInstruction

    status: BlueprintResolutionStatus

    fallback_count: int = 0
    exact_match_count: int = 0

    warnings: list[str] = Field(
        default_factory=list,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @property
    def uses_fallbacks(self) -> bool:
        """Return whether any fallback preset was used."""

        return self.fallback_count > 0

    @property
    def is_resolved(self) -> bool:
        """Return whether the blueprint is usable."""

        return self.status in {
            BlueprintResolutionStatus.RESOLVED,
            BlueprintResolutionStatus.RESOLVED_WITH_FALLBACKS,
            BlueprintResolutionStatus.APPLIED,
        }
