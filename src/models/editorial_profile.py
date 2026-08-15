from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel
from src.models.genre_profile import (
    GenreContentIntelligenceProfile,
    GenreProfileStatus,
    GenreScriptProfile,
    PacingSegment,
)
from src.models.story_blueprint import StoryBeatType

# Only these GenreScriptProfile fields are plain free text (validated
# by clean_text there) - every other field is an enum/bool, and
# blindly overwriting one of those from a raw channel-style string
# would bypass its validation. Keeping this list here, next to the
# one place it's enforced, avoids a channel style silently producing
# an invalid script profile.
_OVERRIDABLE_NARRATION_FIELDS = frozenset(
    {"hook_style", "narrative_style", "sentence_length"}
)


class FormatProfile(MissionBaseModel):
    """
    Structural format for one video, orthogonal to genre (spec:
    "History + Documentary" needs a different structure than
    "History + Investigation" or "History + Top10", despite sharing a
    subject domain). Resolved and merged with a GenreProfile by
    EditorialProfileCompositionService - content-intelligence services
    never read a FormatProfile directly.
    """

    schema_version: str = "1.0"

    format_id: str
    display_name: str
    description: str = ""

    status: GenreProfileStatus = GenreProfileStatus.ACTIVE

    narrative_architecture_hint: str = ""

    pacing_curve_override: list[PacingSegment] = Field(default_factory=list)

    beat_type_bias: list[str] = Field(default_factory=list)

    scene_density_multiplier: float = Field(default=1.0, gt=0.0, le=5.0)

    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("format_id")
    @classmethod
    def validate_format_id(cls, value: str) -> str:
        normalized = value.strip().lower()

        if not normalized.startswith("format."):
            raise ValueError("Format ID must start with 'format.'.")

        if normalized == "format.":
            raise ValueError("Format ID requires a name.")

        return normalized

    @field_validator("display_name")
    @classmethod
    def clean_display_name(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Format profile display name cannot be empty.")

        return cleaned

    @field_validator("beat_type_bias")
    @classmethod
    def validate_beat_type_bias(cls, values: list[str]) -> list[str]:
        valid_types = {beat_type.value for beat_type in StoryBeatType}
        cleaned: list[str] = []

        for value in values:
            normalized = value.strip().lower()

            if normalized not in valid_types:
                raise ValueError(f"'{normalized}' is not a supported story beat type.")

            if normalized not in cleaned:
                cleaned.append(normalized)

        return cleaned

    @property
    def usable(self) -> bool:
        """Return whether this profile may be selected."""

        return self.status == GenreProfileStatus.ACTIVE


class FormatProfileResolutionResult(MissionBaseModel):
    """Result of resolving one format profile with a safe fallback."""

    requested_format_id: str

    resolved_format_id: str | None = None

    profile: FormatProfile | None = None

    found_exact_match: bool = False
    used_fallback: bool = False

    warning: str | None = None

    @property
    def is_resolved(self) -> bool:
        """Return whether a usable format was resolved."""

        return self.profile is not None


class AssumedKnowledgeLevel(str, Enum):
    """How much a target audience is assumed to already know."""

    NOVICE = "novice"
    INFORMED = "informed"
    EXPERT = "expert"


class ViewingBehavior(str, Enum):
    """Expected viewing context for a target audience."""

    BACKGROUND = "background"
    FOCUSED = "focused"
    MOBILE_SCROLL = "mobile_scroll"


class AudienceProfile(MissionBaseModel):
    """
    Structured target-viewer definition for one project (spec:
    audience strategy). Promotes what was previously just a free-text
    `target_audience: str` on AudiencePromise into a reusable,
    structured profile that content-intelligence services can read
    specific fields from instead of parsing prose.
    """

    schema_version: str = "1.0"

    audience_id: str
    display_name: str

    target_viewer_description: str = Field(min_length=1)
    assumed_knowledge_level: AssumedKnowledgeLevel = AssumedKnowledgeLevel.INFORMED

    viewer_motivations: list[str] = Field(default_factory=list)
    viewer_pain_points: list[str] = Field(default_factory=list)

    expected_viewing_behavior: ViewingBehavior = ViewingBehavior.FOCUSED

    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("audience_id")
    @classmethod
    def validate_audience_id(cls, value: str) -> str:
        normalized = value.strip().lower()

        if not normalized.startswith("audience."):
            raise ValueError("Audience ID must start with 'audience.'.")

        if normalized == "audience.":
            raise ValueError("Audience ID requires a name.")

        return normalized

    @field_validator("display_name", "target_viewer_description")
    @classmethod
    def clean_required_text(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Audience profile text cannot be empty.")

        return cleaned

    @field_validator("viewer_motivations", "viewer_pain_points")
    @classmethod
    def clean_text_list(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []

        for value in values:
            stripped = value.strip()

            if stripped and stripped not in cleaned:
                cleaned.append(stripped)

        return cleaned


class ChannelStyleProfile(MissionBaseModel):
    """
    Per-channel narration voice that should override genre defaults
    on specific fields (spec: "always conversational, never formal,
    regardless of genre"). Overrides are sparse and field-scoped, not
    a full profile replacement - see _OVERRIDABLE_NARRATION_FIELDS.
    """

    schema_version: str = "1.0"

    channel_style_id: str
    display_name: str

    narration_overrides: dict[str, str] = Field(default_factory=dict)

    forbidden_phrases: list[str] = Field(default_factory=list)
    signature_phrases: list[str] = Field(default_factory=list)

    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("channel_style_id")
    @classmethod
    def validate_channel_style_id(cls, value: str) -> str:
        normalized = value.strip().lower()

        if not normalized.startswith("channel_style."):
            raise ValueError("Channel style ID must start with 'channel_style.'.")

        if normalized == "channel_style.":
            raise ValueError("Channel style ID requires a name.")

        return normalized

    @field_validator("display_name")
    @classmethod
    def clean_display_name(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Channel style profile display name cannot be empty.")

        return cleaned

    @field_validator("narration_overrides")
    @classmethod
    def validate_narration_overrides(cls, values: dict[str, str]) -> dict[str, str]:
        for field_name, value in values.items():
            if field_name not in _OVERRIDABLE_NARRATION_FIELDS:
                raise ValueError(
                    f"'{field_name}' is not an overridable narration field. "
                    f"Supported fields: {sorted(_OVERRIDABLE_NARRATION_FIELDS)}."
                )

            if not value.strip():
                raise ValueError(
                    f"Narration override for '{field_name}' cannot be empty."
                )

        return values

    @field_validator("forbidden_phrases", "signature_phrases")
    @classmethod
    def clean_phrase_list(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []

        for value in values:
            stripped = value.strip()

            if stripped and stripped not in cleaned:
                cleaned.append(stripped)

        return cleaned


class EditorialProfile(MissionBaseModel):
    """
    The fully resolved, flattened editorial configuration for one
    generation run: genre + format + audience + channel style merged
    with deterministic precedence (channel_style overrides format
    overrides genre, sparse override - see
    EditorialProfileCompositionService). Every content-intelligence
    service reads from this, never resolving multiple profiles
    itself.

    Reuses GenreScriptProfile/GenreContentIntelligenceProfile
    directly rather than inventing a third parallel field set - this
    IS a genre profile's script/content_intelligence sections, just
    already merged with format/channel overrides applied. Persisting
    this snapshot on a project (rather than only the source ids) is
    what keeps a project reproducible if the source profiles change
    later.
    """

    genre_id: str
    format_id: str | None = None
    audience_id: str | None = None
    channel_style_id: str | None = None

    genre_schema_version: str
    format_schema_version: str | None = None

    script: GenreScriptProfile
    content_intelligence: GenreContentIntelligenceProfile
    audience: AudienceProfile | None = None

    beat_type_bias: list[str] = Field(default_factory=list)

    metadata: dict[str, Any] = Field(default_factory=dict)
