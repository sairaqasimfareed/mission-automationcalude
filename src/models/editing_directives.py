from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, field_validator, model_validator

from src.models.base import MissionBaseModel


class DirectiveIntensity(str, Enum):
    """Normalized intensity used by editing directives."""

    VERY_LOW = "very_low"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


class DirectiveTimingMode(str, Enum):
    """How one directive is positioned within a scene."""

    SCENE_START = "scene_start"
    SCENE_MIDDLE = "scene_middle"
    SCENE_END = "scene_end"
    ABSOLUTE_SECONDS = "absolute_seconds"
    RELATIVE_PERCENT = "relative_percent"
    FULL_SCENE = "full_scene"


class EditingDirectiveStatus(str, Enum):
    """Lifecycle state of one editing directive collection."""

    DRAFT = "draft"
    VALIDATED = "validated"
    READY = "ready"
    APPLIED = "applied"
    PARTIALLY_APPLIED = "partially_applied"
    FAILED = "failed"


class CameraDirective(MissionBaseModel):
    """Camera motion requested for one scene."""

    preset_id: str = "camera.none"

    intensity: DirectiveIntensity = (
        DirectiveIntensity.MEDIUM
    )

    start_offset_seconds: float = Field(
        default=0.0,
        ge=0.0,
    )

    end_offset_seconds: float | None = Field(
        default=None,
        ge=0.0,
    )

    zoom_start: float | None = Field(
        default=None,
        gt=0.0,
    )

    zoom_end: float | None = Field(
        default=None,
        gt=0.0,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator("preset_id")
    @classmethod
    def validate_preset_id(
        cls,
        value: str,
    ) -> str:
        return _normalize_registry_id(
            value,
            expected_prefix="camera.",
        )

    @model_validator(mode="after")
    def validate_camera_timing(
        self,
    ) -> CameraDirective:
        if (
            self.end_offset_seconds is not None
            and self.end_offset_seconds
            <= self.start_offset_seconds
        ):
            raise ValueError(
                "Camera directive end offset must be "
                "greater than its start offset."
            )

        return self


class TransitionDirective(MissionBaseModel):
    """Transition requested at a scene boundary."""

    preset_id: str = "transition.cut"

    duration_seconds: float = Field(
        default=0.0,
        ge=0.0,
        le=10.0,
    )

    intensity: DirectiveIntensity = (
        DirectiveIntensity.MEDIUM
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator("preset_id")
    @classmethod
    def validate_preset_id(
        cls,
        value: str,
    ) -> str:
        return _normalize_registry_id(
            value,
            expected_prefix="transition.",
        )

    @model_validator(mode="after")
    def validate_transition_duration(
        self,
    ) -> TransitionDirective:
        if (
            self.preset_id != "transition.cut"
            and self.duration_seconds <= 0
        ):
            raise ValueError(
                "Non-cut transitions require a "
                "positive duration."
            )

        return self


class VisualEffectDirective(MissionBaseModel):
    """One registered visual effect requested for a scene."""

    preset_id: str

    intensity: DirectiveIntensity = (
        DirectiveIntensity.MEDIUM
    )

    timing_mode: DirectiveTimingMode = (
        DirectiveTimingMode.FULL_SCENE
    )

    start_offset_seconds: float = Field(
        default=0.0,
        ge=0.0,
    )

    duration_seconds: float | None = Field(
        default=None,
        gt=0.0,
    )

    relative_position_percent: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
    )

    enabled: bool = True

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator("preset_id")
    @classmethod
    def validate_preset_id(
        cls,
        value: str,
    ) -> str:
        return _normalize_registry_id(
            value,
            expected_prefix="visual.",
        )

    @model_validator(mode="after")
    def validate_timing_configuration(
        self,
    ) -> VisualEffectDirective:
        if (
            self.timing_mode
            == DirectiveTimingMode.RELATIVE_PERCENT
            and self.relative_position_percent is None
        ):
            raise ValueError(
                "Relative-percent timing requires "
                "relative_position_percent."
            )

        return self


class AnimationDirective(MissionBaseModel):
    """One animation or motion-graphics instruction."""

    preset_id: str

    intensity: DirectiveIntensity = (
        DirectiveIntensity.MEDIUM
    )

    start_offset_seconds: float = Field(
        default=0.0,
        ge=0.0,
    )

    duration_seconds: float | None = Field(
        default=None,
        gt=0.0,
    )

    enabled: bool = True

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator("preset_id")
    @classmethod
    def validate_preset_id(
        cls,
        value: str,
    ) -> str:
        return _normalize_registry_id(
            value,
            expected_prefix="animation.",
        )


class MusicDirective(MissionBaseModel):
    """Background-music instruction for one scene."""

    preset_id: str = "music.none"

    intensity: DirectiveIntensity = (
        DirectiveIntensity.LOW
    )

    volume_percent: float = Field(
        default=25.0,
        ge=0.0,
        le=100.0,
    )

    fade_in_seconds: float = Field(
        default=0.0,
        ge=0.0,
    )

    fade_out_seconds: float = Field(
        default=0.0,
        ge=0.0,
    )

    duck_under_voice: bool = True

    enabled: bool = True

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator("preset_id")
    @classmethod
    def validate_preset_id(
        cls,
        value: str,
    ) -> str:
        return _normalize_registry_id(
            value,
            expected_prefix="music.",
        )


class SoundEffectDirective(MissionBaseModel):
    """One sound-effect cue inside a scene."""

    preset_id: str

    timing_mode: DirectiveTimingMode = (
        DirectiveTimingMode.ABSOLUTE_SECONDS
    )

    start_offset_seconds: float = Field(
        default=0.0,
        ge=0.0,
    )

    relative_position_percent: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
    )

    volume_percent: float = Field(
        default=70.0,
        ge=0.0,
        le=100.0,
    )

    intensity: DirectiveIntensity = (
        DirectiveIntensity.MEDIUM
    )

    enabled: bool = True

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator("preset_id")
    @classmethod
    def validate_preset_id(
        cls,
        value: str,
    ) -> str:
        return _normalize_registry_id(
            value,
            expected_prefix="sfx.",
        )

    @model_validator(mode="after")
    def validate_timing_configuration(
        self,
    ) -> SoundEffectDirective:
        if (
            self.timing_mode
            == DirectiveTimingMode.RELATIVE_PERCENT
            and self.relative_position_percent is None
        ):
            raise ValueError(
                "Relative-percent SFX timing requires "
                "relative_position_percent."
            )

        return self


class SubtitleDirective(MissionBaseModel):
    """Subtitle styling and animation instructions."""

    preset_id: str = "subtitle.default"

    enabled: bool = True

    burn_into_video: bool = True

    maximum_words_per_line: int = Field(
        default=8,
        ge=1,
        le=30,
    )

    animation_preset_id: str | None = None

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator("preset_id")
    @classmethod
    def validate_preset_id(
        cls,
        value: str,
    ) -> str:
        return _normalize_registry_id(
            value,
            expected_prefix="subtitle.",
        )

    @field_validator("animation_preset_id")
    @classmethod
    def validate_animation_preset_id(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        return _normalize_registry_id(
            value,
            expected_prefix="animation.",
        )


class SceneEditingDirectives(MissionBaseModel):
    """
    Complete machine-readable editing blueprint for one scene.

    The model contains registry IDs only. Renderer-specific
    instructions are resolved later by the effect registry.
    """

    schema_version: str = "1.0"

    scene_number: int = Field(
        ge=1,
    )

    genre_preset_id: str = "genre.default"

    camera: CameraDirective = Field(
        default_factory=CameraDirective,
    )

    transition_in: TransitionDirective = Field(
        default_factory=TransitionDirective,
    )

    transition_out: TransitionDirective = Field(
        default_factory=TransitionDirective,
    )

    visual_effects: list[
        VisualEffectDirective
    ] = Field(
        default_factory=list,
    )

    animations: list[
        AnimationDirective
    ] = Field(
        default_factory=list,
    )

    music: MusicDirective = Field(
        default_factory=MusicDirective,
    )

    sound_effects: list[
        SoundEffectDirective
    ] = Field(
        default_factory=list,
    )

    subtitles: SubtitleDirective = Field(
        default_factory=SubtitleDirective,
    )

    status: EditingDirectiveStatus = (
        EditingDirectiveStatus.DRAFT
    )

    warnings: list[str] = Field(
        default_factory=list,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator("genre_preset_id")
    @classmethod
    def validate_genre_preset_id(
        cls,
        value: str,
    ) -> str:
        return _normalize_registry_id(
            value,
            expected_prefix="genre.",
        )

    @model_validator(mode="after")
    def validate_duplicate_directives(
        self,
    ) -> SceneEditingDirectives:
        visual_ids = [
            directive.preset_id
            for directive in self.visual_effects
            if directive.enabled
        ]

        if len(visual_ids) != len(set(visual_ids)):
            raise ValueError(
                "Duplicate enabled visual effect IDs "
                "are not allowed in one scene."
            )

        animation_ids = [
            directive.preset_id
            for directive in self.animations
            if directive.enabled
        ]

        if (
            len(animation_ids)
            != len(set(animation_ids))
        ):
            raise ValueError(
                "Duplicate enabled animation IDs "
                "are not allowed in one scene."
            )

        return self

    @property
    def active_effect_count(self) -> int:
        """Return the number of enabled effect instructions."""

        visual_count = sum(
            directive.enabled
            for directive in self.visual_effects
        )

        animation_count = sum(
            directive.enabled
            for directive in self.animations
        )

        sfx_count = sum(
            directive.enabled
            for directive in self.sound_effects
        )

        return (
            visual_count
            + animation_count
            + sfx_count
        )


def _normalize_registry_id(
    value: str,
    *,
    expected_prefix: str,
) -> str:
    """Normalize and validate one registry identifier."""

    normalized = value.strip().lower()

    if not normalized:
        raise ValueError(
            "Directive registry ID cannot be empty."
        )

    if not normalized.startswith(expected_prefix):
        raise ValueError(
            "Directive registry ID must start with "
            f"'{expected_prefix}'."
        )

    allowed_characters = set(
        "abcdefghijklmnopqrstuvwxyz"
        "0123456789._-"
    )

    if any(
        character not in allowed_characters
        for character in normalized
    ):
        raise ValueError(
            "Directive registry ID contains "
            "unsupported characters."
        )

    return normalized