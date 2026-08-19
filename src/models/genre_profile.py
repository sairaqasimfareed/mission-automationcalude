from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, field_validator, model_validator

from src.models.base import MissionBaseModel
from src.models.editing_directives import (
    DirectiveIntensity,
)
from src.models.story_angle import StoryAngleStyle


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


class NarrationPerson(str, Enum):
    """Grammatical person narration is written in for one genre."""

    FIRST = "first"
    THIRD = "third"


class GenreScriptProfile(MissionBaseModel):
    """Script-writing defaults for one genre."""

    tone: GenreTone = GenreTone.NEUTRAL

    pacing: GenrePacingStyle = GenrePacingStyle.MODERATE

    hook_style: str = "standard"

    narrative_style: str = "informative"

    sentence_length: str = "medium"

    use_cliffhangers: bool = False
    use_open_loops: bool = False

    emotional_intensity: DirectiveIntensity = DirectiveIntensity.MEDIUM

    narration_person: NarrationPerson = NarrationPerson.THIRD

    intimacy: DirectiveIntensity = DirectiveIntensity.MEDIUM

    rhetorical_question_use: DirectiveIntensity = DirectiveIntensity.LOW

    sensory_description_density: DirectiveIntensity = DirectiveIntensity.MEDIUM

    slang_intensity: DirectiveIntensity = DirectiveIntensity.LOW

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
            raise ValueError("Genre script profile text cannot be empty.")

        return cleaned


class HookArchetype(str, Enum):
    """Supported opening-hook archetypes for one genre."""

    MYSTERY = "mystery"
    CONTRADICTION = "contradiction"
    DISTURBING_EVENT = "disturbing_event"
    EMOTIONAL_CONFLICT = "emotional_conflict"
    SHOCKING_FACT = "shocking_fact"
    UNANSWERED_QUESTION = "unanswered_question"
    FUTURE_PAYOFF = "future_payoff"
    COLD_OPEN = "cold_open"
    DRAMATIC_MOMENT = "dramatic_moment"
    TRANSFORMATION = "transformation"
    RANKED_LIST_PROMISE = "ranked_list_promise"


class ResearchDepth(str, Enum):
    """How much research rigor one genre requires."""

    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    VERY_HIGH = "very_high"


class UncertainInformationPolicy(str, Enum):
    """How one genre should treat information research could not verify."""

    EXCLUDE = "exclude"
    LABEL_EXPLICITLY = "label_explicitly"
    USE_FREELY = "use_freely"


class ConflictingSourcePolicy(str, Enum):
    """How one genre should treat contradictory research sources."""

    PRESENT_BOTH = "present_both"
    USE_MOST_AUTHORITATIVE = "use_most_authoritative"
    FLAG_CONTROVERSY = "flag_controversy"


class CTAPolicy(str, Enum):
    """How strongly narration should call the viewer to action for one genre."""

    NONE = "none"
    SOFT = "soft"
    DIRECT = "direct"


class RecapPolicy(str, Enum):
    """How much a genre should recap earlier information mid-video."""

    NONE = "none"
    BRIEF = "brief"
    DETAILED = "detailed"


class PacingSegment(MissionBaseModel):
    """One normalized-progress segment of a genre's pacing curve."""

    progress_start: float = Field(ge=0.0, le=1.0)
    progress_end: float = Field(gt=0.0, le=1.0)

    information_density: int = Field(ge=0, le=100)
    emotional_intensity: int = Field(ge=0, le=100)
    reveal_probability: int = Field(ge=0, le=100)
    tension_level: int = Field(ge=0, le=100)

    @model_validator(mode="after")
    def validate_range(self) -> PacingSegment:
        if self.progress_end <= self.progress_start:
            raise ValueError("A pacing segment must end after it starts.")

        return self


class ResearchPolicy(MissionBaseModel):
    """Research rigor requirements for one genre."""

    depth: ResearchDepth = ResearchDepth.MODERATE

    minimum_source_count: int = Field(default=2, ge=0, le=50)

    requires_primary_sources: bool = False

    uncertain_information_policy: UncertainInformationPolicy = (
        UncertainInformationPolicy.LABEL_EXPLICITLY
    )

    conflicting_source_policy: ConflictingSourcePolicy = (
        ConflictingSourcePolicy.PRESENT_BOTH
    )


class CharacterPolicy(MissionBaseModel):
    """
    Character requirements for one genre.

    Only set on genres where characters are a meaningful editorial
    concern (storytelling, horror, survival) - left unset (None) on
    GenreContentIntelligenceProfile for informational genres
    (documentary, top10, medical) so a quality gate can skip
    character-depth scoring entirely rather than scoring an
    irrelevant dimension.
    """

    requires_protagonist: bool = False
    requires_antagonist_or_conflict: bool = False
    allow_dialogue: bool = False

    maximum_character_count: int = Field(default=0, ge=0, le=20)


class GenreContentIntelligenceProfile(MissionBaseModel):
    """
    Genre-specific behavior for the content intelligence engine
    (strategy through script generation).

    Narration tone, hook style, sentence length, use of cliffhangers/
    open loops, emotional intensity, person, intimacy, and sensory
    density already have a home on GenreScriptProfile above - this
    profile only adds the dimensions with no existing equivalent:
    which story angle styles suit this genre, narrative-architecture
    guidance, a structured pacing curve, hook archetype policy,
    retention/reveal density, research rigor, in-narration
    call-to-action policy, quality thresholds, character policy, and
    scene/visual density recommendations for the scene planner.
    """

    preferred_angle_styles: list[str] = Field(
        default_factory=list,
    )

    narrative_architecture_hint: str = ""

    pacing_curve: list[PacingSegment] = Field(
        default_factory=list,
    )

    preferred_hook_archetypes: list[HookArchetype] = Field(
        default_factory=list,
    )

    forbidden_hook_archetypes: list[HookArchetype] = Field(
        default_factory=list,
    )

    hook_intensity: DirectiveIntensity = DirectiveIntensity.MEDIUM

    allow_context_before_hook: bool = False

    reveal_density_per_minute: float = Field(
        default=2.0,
        gt=0.0,
        le=20.0,
    )

    pattern_interrupt_frequency: DirectiveIntensity = DirectiveIntensity.MEDIUM

    recap_policy: RecapPolicy = RecapPolicy.NONE

    research_policy: ResearchPolicy = Field(
        default_factory=ResearchPolicy,
    )

    cta_policy: CTAPolicy = CTAPolicy.SOFT

    forbidden_cta_positions: list[str] = Field(
        default_factory=list,
    )

    quality_thresholds: dict[str, int] = Field(
        default_factory=dict,
    )

    character_policy: CharacterPolicy | None = None

    scene_density_per_minute: float = Field(
        default=6.0,
        gt=0.0,
        le=60.0,
    )

    average_visual_duration_seconds: float = Field(
        default=6.0,
        gt=0.0,
        le=60.0,
    )

    b_roll_density: DirectiveIntensity = DirectiveIntensity.MEDIUM

    establishing_shot_policy: str = "moderate"

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator("preferred_angle_styles")
    @classmethod
    def validate_preferred_angle_styles(
        cls,
        values: list[str],
    ) -> list[str]:
        valid_styles = {style.value for style in StoryAngleStyle}
        cleaned: list[str] = []

        for value in values:
            normalized = value.strip().lower()

            if normalized not in valid_styles:
                raise ValueError(
                    f"'{normalized}' is not a supported story angle style."
                )

            if normalized not in cleaned:
                cleaned.append(normalized)

        return cleaned

    @field_validator("forbidden_cta_positions")
    @classmethod
    def clean_forbidden_cta_positions(
        cls,
        values: list[str],
    ) -> list[str]:
        cleaned: list[str] = []

        for value in values:
            normalized = value.strip().lower()

            if normalized and normalized not in cleaned:
                cleaned.append(normalized)

        return cleaned

    @field_validator("quality_thresholds")
    @classmethod
    def validate_quality_thresholds(
        cls,
        values: dict[str, int],
    ) -> dict[str, int]:
        for dimension, threshold in values.items():
            if not dimension.strip():
                raise ValueError("Quality threshold dimension name cannot be empty.")

            if not 0 <= threshold <= 100:
                raise ValueError(
                    f"Quality threshold for '{dimension}' must be between 0 and 100."
                )

        return values

    @field_validator("establishing_shot_policy")
    @classmethod
    def clean_establishing_shot_policy(
        cls,
        value: str,
    ) -> str:
        cleaned = value.strip().lower()

        if not cleaned:
            raise ValueError("Establishing shot policy cannot be empty.")

        return cleaned

    @model_validator(mode="after")
    def validate_hook_archetypes(self) -> GenreContentIntelligenceProfile:
        overlap = set(self.preferred_hook_archetypes) & set(
            self.forbidden_hook_archetypes
        )

        if overlap:
            raise ValueError(
                "A hook archetype cannot be both preferred and forbidden: "
                f"{sorted(archetype.value for archetype in overlap)}."
            )

        return self


class GenreVoiceProfile(MissionBaseModel):
    """Provider-independent voice defaults for one genre."""

    voice_profile_id: str = "voice.neutral_narrator"

    emotion: str = "neutral"

    pace: GenrePacingStyle = GenrePacingStyle.MODERATE

    energy: DirectiveIntensity = DirectiveIntensity.MEDIUM

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
            raise ValueError("Genre voice profile text cannot be empty.")

        return cleaned


class GenreEditingProfile(MissionBaseModel):
    """Default editing-directive references for one genre."""

    camera_preset_id: str = "camera.none"

    transition_in_preset_id: str = "transition.cut"

    transition_out_preset_id: str = "transition.cut"

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

    subtitle_preset_id: str = "subtitle.default"

    subtitle_animation_preset_id: str | None = None

    effect_intensity: DirectiveIntensity = DirectiveIntensity.MEDIUM

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

    @field_validator("subtitle_animation_preset_id")
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

    @field_validator("sound_effect_preset_ids")
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

        if uses_non_cut_transition and self.default_transition_duration_seconds <= 0:
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
            raise ValueError("Genre SEO profile text cannot be empty.")

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

    status: GenreProfileStatus = GenreProfileStatus.ACTIVE

    fallback_genre_id: str | None = "genre.default"

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

    content_intelligence: GenreContentIntelligenceProfile = Field(
        default_factory=GenreContentIntelligenceProfile,
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
            raise ValueError("Genre profile text cannot be empty.")

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

            if normalized and normalized not in cleaned:
                cleaned.append(normalized)

        return cleaned

    @model_validator(mode="after")
    def validate_fallback(
        self,
    ) -> GenreProfile:
        if self.fallback_genre_id == self.genre_id:
            raise ValueError("A genre profile cannot use itself " "as its fallback.")

        if self.genre_id == "genre.default" and self.fallback_genre_id is not None:
            raise ValueError(
                "The default genre profile cannot " "declare another fallback."
            )

        return self

    @property
    def usable(self) -> bool:
        """Return whether this profile may be selected."""

        return self.status == GenreProfileStatus.ACTIVE


class GenreProfileResolutionResult(MissionBaseModel):
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
        raise ValueError("Registry ID cannot be empty.")

    if not normalized.startswith(expected_prefix):
        raise ValueError("Registry ID must start with " f"'{expected_prefix}'.")

    allowed_characters = set("abcdefghijklmnopqrstuvwxyz" "0123456789._-")

    if any(character not in allowed_characters for character in normalized):
        raise ValueError("Registry ID contains unsupported characters.")

    if normalized == expected_prefix:
        raise ValueError("Registry ID requires a name.")

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
