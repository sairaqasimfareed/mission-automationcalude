from __future__ import annotations

from enum import Enum

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel


class ProviderPreference(MissionBaseModel):
    """Provider preference for one production category."""

    preferred_profile_id: str | None = None
    fallback_profile_ids: list[str] = Field(default_factory=list)
    auto_select: bool = True
    lock_preferred_provider: bool = False

    @field_validator("fallback_profile_ids")
    @classmethod
    def clean_fallback_profile_ids(
        cls,
        values: list[str],
    ) -> list[str]:
        cleaned: list[str] = []

        for value in values:
            normalized = value.strip()

            if not normalized:
                continue

            if normalized not in cleaned:
                cleaned.append(normalized)

        return cleaned


class ReviewerMode(str, Enum):
    """
    When the Reviewer LLM role actually runs (Content Studio Redesign,
    Phase 2). ON_DEMAND means a human explicitly triggers "Review" on
    an artifact; AUTOMATIC_AT_APPROVAL_GATES means the reviewer runs
    on its own right before a configured approval gate, without
    becoming the artifact's author - it only ever produces a
    ReviewerResult a human or the Primary LLM then acts on.
    """

    ON_DEMAND = "on_demand"
    AUTOMATIC_AT_APPROVAL_GATES = "automatic_at_approval_gates"


class ReviewerConfiguration(MissionBaseModel):
    """
    Project-level Reviewer LLM role - distinct from `ProviderPreference`
    because "review without authoring" is a content-generation-specific
    concept, not something that applies to every provider category the
    way preferred/fallback selection does (there's no sense in which a
    stock-footage provider gets "reviewed"). `reviewer_profile_id`
    being None means no Reviewer is configured for this project at all
    - a legitimate, supported choice, not a missing default.
    """

    reviewer_profile_id: str | None = None
    mode: ReviewerMode = ReviewerMode.ON_DEMAND

    @field_validator("reviewer_profile_id")
    @classmethod
    def clean_reviewer_profile_id(cls, value: str | None) -> str | None:
        if value is None:
            return None

        cleaned = value.strip()

        return cleaned or None


class ProviderPreferences(MissionBaseModel):
    """Project-level provider preferences by category."""

    schema_version: str = "1.0"

    llm: ProviderPreference = Field(default_factory=ProviderPreference)
    video: ProviderPreference = Field(default_factory=ProviderPreference)
    voice: ProviderPreference = Field(default_factory=ProviderPreference)
    image: ProviderPreference = Field(default_factory=ProviderPreference)
    stock_video: ProviderPreference = Field(default_factory=ProviderPreference)
    stock_image: ProviderPreference = Field(default_factory=ProviderPreference)
    music: ProviderPreference = Field(default_factory=ProviderPreference)
    sound_effects: ProviderPreference = Field(default_factory=ProviderPreference)
    upload: ProviderPreference = Field(default_factory=ProviderPreference)

    # The redesign's "Reviewer LLM" role. Primary maps to llm.preferred_
    # profile_id and Fallback to llm.fallback_profile_ids above - both
    # already existed and needed no new model; Reviewer is the one
    # genuinely new role, see ReviewerConfiguration.
    reviewer: ReviewerConfiguration = Field(default_factory=ReviewerConfiguration)
