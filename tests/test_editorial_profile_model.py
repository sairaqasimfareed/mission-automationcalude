from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.editorial_profile import (
    AssumedKnowledgeLevel,
    AudienceProfile,
    ChannelStyleProfile,
    EditorialProfile,
    FormatProfile,
    ViewingBehavior,
)
from src.models.genre_profile import (
    GenreContentIntelligenceProfile,
    GenreScriptProfile,
)


def _format_profile(**overrides: object) -> FormatProfile:
    base: dict[str, object] = dict(
        format_id="format.documentary",
        display_name="Documentary",
    )
    base.update(overrides)
    return FormatProfile(**base)


def _audience_profile(**overrides: object) -> AudienceProfile:
    base: dict[str, object] = dict(
        audience_id="audience.curious_adults",
        display_name="Curious Adults",
        target_viewer_description="Adults who enjoy long-form deep dives.",
    )
    base.update(overrides)
    return AudienceProfile(**base)


def _channel_style(**overrides: object) -> ChannelStyleProfile:
    base: dict[str, object] = dict(
        channel_style_id="channel_style.conversational",
        display_name="Conversational",
    )
    base.update(overrides)
    return ChannelStyleProfile(**base)


def test_format_profile_requires_format_prefix() -> None:
    with pytest.raises(ValidationError, match="must start with 'format.'"):
        _format_profile(format_id="documentary")


def test_format_profile_rejects_unsupported_beat_type() -> None:
    with pytest.raises(ValidationError, match="not a supported story beat type"):
        _format_profile(beat_type_bias=["not_a_real_beat"])


def test_format_profile_deduplicates_beat_type_bias() -> None:
    profile = _format_profile(beat_type_bias=["hook", "reveal", "hook"])

    assert profile.beat_type_bias == ["hook", "reveal"]


def test_format_profile_usable_reflects_status() -> None:
    assert _format_profile().usable is True


def test_audience_profile_requires_audience_prefix() -> None:
    with pytest.raises(ValidationError, match="must start with 'audience.'"):
        _audience_profile(audience_id="curious_adults")


def test_audience_profile_defaults() -> None:
    profile = _audience_profile()

    assert profile.assumed_knowledge_level == AssumedKnowledgeLevel.INFORMED
    assert profile.expected_viewing_behavior == ViewingBehavior.FOCUSED


def test_audience_profile_deduplicates_motivations() -> None:
    profile = _audience_profile(
        viewer_motivations=["curiosity", "entertainment", "curiosity"]
    )

    assert profile.viewer_motivations == ["curiosity", "entertainment"]


def test_channel_style_requires_channel_style_prefix() -> None:
    with pytest.raises(ValidationError, match="must start with 'channel_style.'"):
        _channel_style(channel_style_id="conversational")


def test_channel_style_rejects_non_overridable_field() -> None:
    with pytest.raises(ValidationError, match="not an overridable narration field"):
        _channel_style(narration_overrides={"tone": "friendly"})


def test_channel_style_rejects_empty_override_value() -> None:
    with pytest.raises(ValidationError, match="cannot be empty"):
        _channel_style(narration_overrides={"hook_style": "   "})


def test_channel_style_accepts_overridable_fields() -> None:
    profile = _channel_style(
        narration_overrides={
            "hook_style": "conversational",
            "narrative_style": "casual",
        }
    )

    assert profile.narration_overrides == {
        "hook_style": "conversational",
        "narrative_style": "casual",
    }


def test_editorial_profile_constructs_from_genre_sub_profiles() -> None:
    profile = EditorialProfile(
        genre_id="genre.documentary",
        genre_schema_version="1.0",
        script=GenreScriptProfile(),
        content_intelligence=GenreContentIntelligenceProfile(),
    )

    assert profile.format_id is None
    assert profile.audience is None
