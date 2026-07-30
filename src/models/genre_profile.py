from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, field_validator, model_validator

from src.models.base import MissionBaseModel
from src.models.editing_directives import (
    DirectiveIntensity,
)


class GenreProfileStatus(str, Enum):
    """Lifecycle status of one universal genre profile."""

    ACTIVE = "active"
    DEPRECATED = "deprecated"
    DISABLED = "disabled"


class GenrePacingStyle(str, Enum):
    """Normalized production pacing for one genre."""

    VERY_SLOW = "very_slow"
    SLOW = "slow"
    MODERATE = "moderate"
    FAST = "fast"
    VERY_FAST = "very_fast"
    DYNAMIC = "dynamic"


class GenreTone(str, Enum):
    """High-level creative tone for one genre."""

    NEUTRAL = "neutral"
    DARK = "dark"
    SUSPENSEFUL = "suspenseful"
    AUTHORITATIVE = "authoritative"
    EDUCATIONAL = "educational"
    EMOTIONAL = "emotional"
    ENERGETIC = "energetic"
    INSPIRATIONAL = "inspirational"
    CINEMATIC = "cinematic"
    FRIENDLY = "friendly"


class GenreScriptProfile(MissionBaseModel):
    """Script-writing defaults for one genre."""

    tone: GenreTone = GenreTone.NEUTRAL

    pacing: GenrePacingStyle = (
        GenrePacingStyle.MODERATE
    )

    hook_style: str = "standard"

    narrative_style: str = "informative"

    sentence_length: str = "medium"

    use_cliffhangers: bool = False
    use_open_loops: bool = False

    emotional_intensity: DirectiveIntensity = (
        DirectiveIntensity.MEDIUM
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator(
        "hook_style",
        "narrative_style",
        "sentence_length",
    )
    @classmethod
    def clean_text(
        cls,
        value: str,
    ) -> str:
        cleaned = value.strip().lower()

        if not cleaned:
            raise ValueError(
                "Genre script profile text cannot be empty."
            )

        return cleaned


class GenreVoiceProfile(MissionBaseModel):
    """Provider-independent voice defaults for one genre."""

    voice_profile_id: str = "voice.neutral_narrator"

    emotion: str = "neutral"

    pace: GenrePacingStyle = (
        GenrePacingStyle.MODERATE
    )

    energy: DirectiveIntensity = (
        DirectiveIntensity.MEDIUM
    )

    pitch_style: str = "natural"

    pause_style: str = "natural"

    emphasis_style: str = "balanced"

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator("voice_profile_id")
    @classmethod
    def validate_voice_profile_id(
        cls,
        value: str,
    ) -> str:
        return _normalize_prefixed_id(
            value,
            expected_prefix="voice.",
        )

    @field_validator(
        "emotion",
        "pitch_style",
        "pause_style",
        "emphasis_style",
    )
    @classmethod
    def clean_text(
        cls,
        value: str,
    ) -> str:
        cleaned = value.strip().lower()

        if not cleaned:
            raise ValueError(
                "Genre voice profile text cannot be empty."
            )

        return cleaned


class GenreEditingProfile(MissionBaseModel):
    """Default editing-directive references for one genre."""

    camera_preset_id: str = "camera.none"

    transition_in_preset_id: str = (
        "transition.cut"
    )

    transition_out_preset_id: str = (
        "transition.cut"
    )

    visual_preset_ids: list[str] = Field(
        default_factory=list,
    )

    animation_preset_ids: list[str] = Field(
        default_factory=list,
    )

    music_preset_id: str = "music.none"

    sound_effect_preset_ids: list[str] = Field(
        default_factory=list,
    )

    subtitle_preset_id: str = (
        "subtitle.default"
    )

    subtitle_animation_preset_id: (
        str | None
    ) = None

    effect_intensity: DirectiveIntensity = (
        DirectiveIntensity.MEDIUM
    )

    maximum_active_effects: int = Field(
        default=8,
        ge=0,
        le=50,
    )

    default_transition_duration_seconds: float = Field(
        default=0.0,
        ge=0.0,
        le=10.0,
    )

    default_music_volume_percent: float = Field(
        default=25.0,
        ge=0.0,
        le=100.0,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator("camera_preset_id")
    @classmethod
    def validate_camera_id(
        cls,
        value: str,
    ) -> str:
        return _normalize_prefixed_id(
            value,
            expected_prefix="camera.",
        )

    @field_validator(
        "transition_in_preset_id",
        "transition_out_preset_id",
    )
    @classmethod
    def validate_transition_id(
        cls,
        value: str,
    ) -> str:
        return _normalize_prefixed_id(
            value,
            expected_prefix="transition.",
        )

    @field_validator("music_preset_id")
    @classmethod
    def validate_music_id(
        cls,
        value: str,
    ) -> str:
        return _normalize_prefixed_id(
            value,
            expected_prefix="music.",
        )

    @field_validator("subtitle_preset_id")
    @classmethod
    def validate_subtitle_id(
        cls,
        value: str,
    ) -> str:
        return _normalize_prefixed_id(
            value,
            expected_prefix="subtitle.",
        )

    @field_validator(
        "subtitle_animation_preset_id"
    )
    @classmethod
    def validate_subtitle_animation_id(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        return _normalize_prefixed_id(
            value,
            expected_prefix="animation.",
        )

    @field_validator("visual_preset_ids")
    @classmethod
    def validate_visual_ids(
        cls,
        values: list[str],
    ) -> list[str]:
        return _normalize_id_list(
            values,
            expected_prefix="visual.",
        )

    @field_validator("animation_preset_ids")
    @classmethod
    def validate_animation_ids(
        cls,
        values: list[str],
    ) -> list[str]:
        return _normalize_id_list(
            values,
            expected_prefix="animation.",
        )

    @field_validator(
        "sound_effect_preset_ids"
    )
    @classmethod
    def validate_sfx_ids(
        cls,
        values: list[str],
    ) -> list[str]:
        return _normalize_id_list(
            values,
            expected_prefix="sfx.",
        )

    @model_validator(mode="after")
    def validate_transition_configuration(
        self,
    ) -> GenreEditingProfile:
        uses_non_cut_transition = any(
            preset_id != "transition.cut"
            for preset_id in {
                self.transition_in_preset_id,
                self.transition_out_preset_id,
            }
        )

        if (
            uses_non_cut_transition
            and self.default_transition_duration_seconds
            <= 0
        ):
            raise ValueError(
                "Genre profiles using non-cut transitions "
                "require a positive default duration."
            )

        return self


class GenreThumbnailProfile(MissionBaseModel):
    """Thumbnail-generation defaults for one genre."""

    style_id: str = "thumbnail.default"

    composition: str = "balanced"

    color_mood: str = "neutral"

    text_style: str = "clear"

    use_faces: bool = False

    maximum_words: int = Field(
        default=5,
        ge=0,
        le=20,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator("style_id")
    @classmethod
    def validate_style_id(
        cls,
        value: str,
    ) -> str:
        return _normalize_prefixed_id(
            value,
            expected_prefix="thumbnail.",
        )


class GenreSEOProfile(MissionBaseModel):
    """SEO and publishing-text defaults for one genre."""

    title_tone: GenreTone = GenreTone.NEUTRAL

    description_style: str = "informative"

    keyword_style: str = "balanced"

    hashtag_style: str = "relevant"

    call_to_action_style: str = "subtle"

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator(
        "description_style",
        "keyword_style",
        "hashtag_style",
        "call_to_action_style",
    )
    @classmethod
    def clean_text(
        cls,
        value: str,
    ) -> str:
        cleaned = value.strip().lower()

        if not cleaned:
            raise ValueError(
                "Genre SEO profile text cannot be empty."
            )

        return cleaned


class GenreProfile(MissionBaseModel):
    """
    Universal production profile for one content genre.

    This profile stores provider-independent creative defaults
    for script, voice, editing, thumbnail, and SEO modules.
    """

    schema_version: str = "1.0"

    genre_id: str

    display_name: str

    description: str = ""

    version: str = "1.0.0"

    status: GenreProfileStatus = (
        GenreProfileStatus.ACTIVE
    )

    fallback_genre_id: str | None = (
        "genre.default"
    )

    script: GenreScriptProfile = Field(
        default_factory=GenreScriptProfile,
    )

    voice: GenreVoiceProfile = Field(
        default_factory=GenreVoiceProfile,
    )

    editing: GenreEditingProfile = Field(
        default_factory=GenreEditingProfile,
    )

    thumbnail: GenreThumbnailProfile = Field(
        default_factory=GenreThumbnailProfile,
    )

    seo: GenreSEOProfile = Field(
        default_factory=GenreSEOProfile,
    )

    tags: list[str] = Field(
        default_factory=list,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator("genre_id")
    @classmethod
    def normalize_genre_id(
        cls,
        value: str,
    ) -> str:
        return _normalize_prefixed_id(
            value,
            expected_prefix="genre.",
        )

    @field_validator("fallback_genre_id")
    @classmethod
    def normalize_fallback_genre_id(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        return _normalize_prefixed_id(
            value,
            expected_prefix="genre.",
        )

    @field_validator(
        "display_name",
        "version",
    )
    @classmethod
    def clean_required_text(
        cls,
        value: str,
    ) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError(
                "Genre profile text cannot be empty."
            )

        return cleaned

    @field_validator("description")
    @classmethod
    def clean_description(
        cls,
        value: str,
    ) -> str:
        return value.strip()

    @field_validator("tags")
    @classmethod
    def clean_tags(
        cls,
        values: list[str],
    ) -> list[str]:
        cleaned: list[str] = []

        for value in values:
            normalized = value.strip().lower()

            if (
                normalized
                and normalized not in cleaned
            ):
                cleaned.append(normalized)

        return cleaned

    @model_validator(mode="after")
    def validate_fallback(
        self,
    ) -> GenreProfile:
        if self.fallback_genre_id == self.genre_id:
            raise ValueError(
                "A genre profile cannot use itself "
                "as its fallback."
            )

        if (
            self.genre_id == "genre.default"
            and self.fallback_genre_id is not None
        ):
            raise ValueError(
                "The default genre profile cannot "
                "declare another fallback."
            )

        return self

    @property
    def usable(self) -> bool:
        """Return whether this profile may be selected."""

        return (
            self.status
            == GenreProfileStatus.ACTIVE
        )


class GenreProfileResolutionResult(
    MissionBaseModel
):
    """Result of resolving one universal genre profile."""

    requested_genre_id: str

    resolved_genre_id: str | None = None

    profile: GenreProfile | None = None

    found_exact_match: bool = False
    used_fallback: bool = False

    warning: str | None = None

    @property
    def is_resolved(self) -> bool:
        """Return whether a usable genre was resolved."""

        return self.profile is not None


def _normalize_prefixed_id(
    value: str,
    *,
    expected_prefix: str,
) -> str:
    """Normalize one provider-independent registry ID."""

    normalized = value.strip().lower()

    if not normalized:
        raise ValueError(
            "Registry ID cannot be empty."
        )

    if not normalized.startswith(
        expected_prefix
    ):
        raise ValueError(
            "Registry ID must start with "
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
            "Registry ID contains unsupported characters."
        )

    if normalized == expected_prefix:
        raise ValueError(
            "Registry ID requires a name."
        )

    return normalized


def _normalize_id_list(
    values: list[str],
    *,
    expected_prefix: str,
) -> list[str]:
    """Normalize and deduplicate one list of registry IDs."""

    cleaned: list[str] = []

    for value in values:
        normalized = _normalize_prefixed_id(
            value,
            expected_prefix=expected_prefix,
        )

        if normalized not in cleaned:
            cleaned.append(normalized)

    return cleaned