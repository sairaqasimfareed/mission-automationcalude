from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, field_validator, model_validator

from src.models.base import MissionBaseModel


class VoiceDirectiveStatus(str, Enum):
    """Lifecycle state of one scene voice directive."""

    DRAFT = "draft"
    VALIDATED = "validated"
    READY = "ready"
    GENERATED = "generated"
    PARTIALLY_GENERATED = "partially_generated"
    FAILED = "failed"


class VoiceEmotion(str, Enum):
    """Provider-independent narration emotion."""

    NEUTRAL = "neutral"
    CALM = "calm"
    WARM = "warm"
    FRIENDLY = "friendly"
    SERIOUS = "serious"
    AUTHORITATIVE = "authoritative"
    EMOTIONAL = "emotional"
    SAD = "sad"
    HAPPY = "happy"
    EXCITED = "excited"
    SUSPENSEFUL = "suspenseful"
    FEARFUL = "fearful"
    TENSE = "tense"
    MYSTERIOUS = "mysterious"
    DRAMATIC = "dramatic"
    INSPIRATIONAL = "inspirational"


class VoicePace(str, Enum):
    """Normalized narration pace."""

    VERY_SLOW = "very_slow"
    SLOW = "slow"
    MODERATE = "moderate"
    FAST = "fast"
    VERY_FAST = "very_fast"
    DYNAMIC = "dynamic"


class VoiceEnergy(str, Enum):
    """Normalized narration energy."""

    VERY_LOW = "very_low"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


class VoicePitchStyle(str, Enum):
    """High-level provider-independent pitch style."""

    VERY_DEEP = "very_deep"
    DEEP = "deep"
    NATURAL = "natural"
    BRIGHT = "bright"
    HIGH = "high"


class VoicePauseStyle(str, Enum):
    """Default pause behavior for narration."""

    MINIMAL = "minimal"
    NATURAL = "natural"
    DRAMATIC = "dramatic"
    FREQUENT = "frequent"
    CINEMATIC = "cinematic"


class VoiceEmphasisStyle(str, Enum):
    """Default word-emphasis behavior."""

    NONE = "none"
    SUBTLE = "subtle"
    BALANCED = "balanced"
    SELECTIVE = "selective"
    DRAMATIC = "dramatic"
    EMOTIONAL = "emotional"
    RANK_NUMBERS = "rank_numbers"


class VoiceDirectiveSource(str, Enum):
    """Source that produced a voice instruction."""

    SYSTEM_DEFAULT = "system_default"
    GENRE_PROFILE = "genre_profile"
    SCRIPT_DIRECTIVE = "script_directive"
    SCENE_OVERRIDE = "scene_override"
    USER_OVERRIDE = "user_override"


class PronunciationDirective(MissionBaseModel):
    """Custom pronunciation for one word or phrase."""

    text: str

    pronunciation: str

    alphabet: str = "ipa"

    language_code: str | None = None

    case_sensitive: bool = False

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator(
        "text",
        "pronunciation",
        "alphabet",
    )
    @classmethod
    def clean_required_text(
        cls,
        value: str,
    ) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Pronunciation directive text " "cannot be empty.")

        return cleaned

    @field_validator("language_code")
    @classmethod
    def clean_language_code(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        cleaned = value.strip().lower()

        if not cleaned:
            return None

        return cleaned


class VoicePauseDirective(MissionBaseModel):
    """Explicit pause requested inside one narration segment."""

    after_text: str | None = None

    at_character_index: int | None = Field(
        default=None,
        ge=0,
    )

    duration_seconds: float = Field(
        default=0.5,
        gt=0.0,
        le=10.0,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator("after_text")
    @classmethod
    def clean_after_text(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        cleaned = value.strip()

        if not cleaned:
            return None

        return cleaned

    @model_validator(mode="after")
    def validate_pause_location(
        self,
    ) -> VoicePauseDirective:
        if self.after_text is None and self.at_character_index is None:
            raise ValueError(
                "Voice pause requires after_text or " "at_character_index."
            )

        return self


class VoiceEmphasisDirective(MissionBaseModel):
    """Explicit emphasis for one word or phrase."""

    text: str

    strength: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
    )

    occurrence: int | None = Field(
        default=None,
        ge=1,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator("text")
    @classmethod
    def clean_text(
        cls,
        value: str,
    ) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Voice emphasis text cannot be empty.")

        return cleaned


class VoiceProviderPreferences(MissionBaseModel):
    """
    Optional provider selection preferences.

    These fields do not contain API keys and do not directly
    execute provider-specific generation.
    """

    preferred_provider: str | None = None

    preferred_model: str | None = None

    preferred_voice_id: str | None = None

    preferred_output_format: str = "mp3"

    fallback_providers: list[str] = Field(
        default_factory=list,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator(
        "preferred_provider",
        "preferred_model",
        "preferred_voice_id",
    )
    @classmethod
    def clean_optional_text(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        cleaned = value.strip()

        if not cleaned:
            return None

        return cleaned

    @field_validator("preferred_output_format")
    @classmethod
    def validate_output_format(
        cls,
        value: str,
    ) -> str:
        normalized = value.strip().lower()

        supported_formats = {
            "mp3",
            "wav",
            "aac",
            "ogg",
            "flac",
        }

        if normalized not in supported_formats:
            raise ValueError("Unsupported voice output format.")

        return normalized

    @field_validator("fallback_providers")
    @classmethod
    def clean_fallback_providers(
        cls,
        values: list[str],
    ) -> list[str]:
        cleaned: list[str] = []

        for value in values:
            normalized = value.strip()

            if normalized and normalized not in cleaned:
                cleaned.append(normalized)

        return cleaned


class SceneVoiceDirectives(MissionBaseModel):
    """
    Complete machine-readable voice blueprint request for one scene.

    This model contains creative and normalized voice instructions.
    Provider-specific settings are produced later by a resolver.
    """

    schema_version: str = "1.0"

    scene_number: int = Field(
        ge=1,
    )

    voice_profile_id: str = "voice.neutral_narrator"

    fallback_voice_profile_id: str | None = "voice.neutral_narrator"

    language: str = "English"

    language_code: str = "en"

    emotion: VoiceEmotion = VoiceEmotion.NEUTRAL

    pace: VoicePace = VoicePace.MODERATE

    energy: VoiceEnergy = VoiceEnergy.MEDIUM

    pitch_style: VoicePitchStyle = VoicePitchStyle.NATURAL

    pause_style: VoicePauseStyle = VoicePauseStyle.NATURAL

    emphasis_style: VoiceEmphasisStyle = VoiceEmphasisStyle.BALANCED

    speed: float = Field(
        default=1.0,
        ge=0.5,
        le=2.0,
    )

    pitch_adjustment: float = Field(
        default=0.0,
        ge=-20.0,
        le=20.0,
    )

    volume_gain_db: float = Field(
        default=0.0,
        ge=-20.0,
        le=20.0,
    )

    stability: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
    )

    similarity_boost: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
    )

    style_strength: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
    )

    speaker_boost: bool = True

    pause_before_seconds: float = Field(
        default=0.0,
        ge=0.0,
        le=30.0,
    )

    pause_after_seconds: float = Field(
        default=0.0,
        ge=0.0,
        le=30.0,
    )

    pronunciation_directives: list[PronunciationDirective] = Field(
        default_factory=list,
    )

    pause_directives: list[VoicePauseDirective] = Field(
        default_factory=list,
    )

    emphasis_directives: list[VoiceEmphasisDirective] = Field(
        default_factory=list,
    )

    provider_preferences: VoiceProviderPreferences = Field(
        default_factory=VoiceProviderPreferences,
    )

    source: VoiceDirectiveSource = VoiceDirectiveSource.SYSTEM_DEFAULT

    status: VoiceDirectiveStatus = VoiceDirectiveStatus.DRAFT

    warnings: list[str] = Field(
        default_factory=list,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator(
        "voice_profile_id",
        "fallback_voice_profile_id",
    )
    @classmethod
    def validate_voice_profile_id(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        return _normalize_voice_profile_id(value)

    @field_validator("language")
    @classmethod
    def clean_language(
        cls,
        value: str,
    ) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Voice directive language " "cannot be empty.")

        return cleaned

    @field_validator("language_code")
    @classmethod
    def clean_language_code(
        cls,
        value: str,
    ) -> str:
        cleaned = value.strip().lower()

        if not cleaned:
            raise ValueError("Voice language code cannot be empty.")

        allowed_characters = set("abcdefghijklmnopqrstuvwxyz-")

        if any(character not in allowed_characters for character in cleaned):
            raise ValueError("Voice language code contains " "unsupported characters.")

        return cleaned

    @model_validator(mode="after")
    def validate_voice_directives(
        self,
    ) -> SceneVoiceDirectives:
        if self.fallback_voice_profile_id == self.voice_profile_id:
            self.fallback_voice_profile_id = None

        pronunciation_keys = [
            (directive.text.lower() if not directive.case_sensitive else directive.text)
            for directive in (self.pronunciation_directives)
        ]

        if len(pronunciation_keys) != len(set(pronunciation_keys)):
            raise ValueError("Duplicate pronunciation directives " "are not allowed.")

        emphasis_keys = [
            (
                directive.text.lower(),
                directive.occurrence,
            )
            for directive in (self.emphasis_directives)
        ]

        if len(emphasis_keys) != len(set(emphasis_keys)):
            raise ValueError("Duplicate emphasis directives " "are not allowed.")

        return self

    @property
    def explicit_instruction_count(self) -> int:
        """Return the number of explicit speech instructions."""

        return (
            len(self.pronunciation_directives)
            + len(self.pause_directives)
            + len(self.emphasis_directives)
        )


def _normalize_voice_profile_id(
    value: str,
) -> str:
    """Normalize and validate one voice profile ID."""

    normalized = value.strip().lower()

    if not normalized:
        raise ValueError("Voice profile ID cannot be empty.")

    if not normalized.startswith("voice."):
        raise ValueError("Voice profile ID must start " "with 'voice.'.")

    if normalized == "voice.":
        raise ValueError("Voice profile ID requires a name.")

    allowed_characters = set("abcdefghijklmnopqrstuvwxyz" "0123456789._-")

    if any(character not in allowed_characters for character in normalized):
        raise ValueError("Voice profile ID contains " "unsupported characters.")

    return normalized
