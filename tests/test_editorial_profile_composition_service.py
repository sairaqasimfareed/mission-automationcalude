from __future__ import annotations

from src.models.editorial_profile import AudienceProfile, ChannelStyleProfile
from src.services.editorial_profile_composition_service import (
    EditorialProfileCompositionService,
)
from src.services.format_profile_registry_service import (
    FormatProfileRegistryService,
)
from src.services.genre_profile_registry_service import (
    GenreProfileRegistryService,
)

genre_registry = GenreProfileRegistryService.with_default_profiles()
format_registry = FormatProfileRegistryService.with_default_profiles()
service = EditorialProfileCompositionService()


def test_compose_genre_only_matches_genre_defaults() -> None:
    genre = genre_registry.get("genre.horror")

    profile = service.compose(genre=genre)

    assert profile.genre_id == "genre.horror"
    assert profile.format_id is None
    assert profile.script == genre.script
    assert profile.content_intelligence == genre.content_intelligence
    assert profile.beat_type_bias == []


def test_format_overrides_narrative_architecture_and_pacing() -> None:
    genre = genre_registry.get("genre.history")
    investigation_format = format_registry.get("format.investigation")

    profile = service.compose(genre=genre, format_profile=investigation_format)

    assert (
        profile.content_intelligence.narrative_architecture_hint
        == investigation_format.narrative_architecture_hint
    )
    assert (
        profile.content_intelligence.pacing_curve
        == investigation_format.pacing_curve_override
    )
    assert profile.beat_type_bias == investigation_format.beat_type_bias
    assert profile.format_id == "format.investigation"


def test_format_scene_density_multiplier_scales_genre_value() -> None:
    genre = genre_registry.get("genre.documentary")
    top10_format = format_registry.get("format.top10")

    profile = service.compose(genre=genre, format_profile=top10_format)

    expected = (
        genre.content_intelligence.scene_density_per_minute
        * top10_format.scene_density_multiplier
    )

    assert profile.content_intelligence.scene_density_per_minute == expected


def test_format_with_no_overrides_leaves_content_intelligence_unchanged() -> None:
    genre = genre_registry.get("genre.horror")
    narrative_format = format_registry.get("format.narrative")

    profile = service.compose(genre=genre, format_profile=narrative_format)

    assert profile.content_intelligence == genre.content_intelligence


def test_channel_style_overrides_script_narration_fields() -> None:
    genre = genre_registry.get("genre.documentary")
    channel_style = ChannelStyleProfile(
        channel_style_id="channel_style.casual_host",
        display_name="Casual Host",
        narration_overrides={"hook_style": "conversational"},
    )

    profile = service.compose(genre=genre, channel_style=channel_style)

    assert profile.script.hook_style == "conversational"
    # Untouched script fields stay genre-derived.
    assert profile.script.tone == genre.script.tone
    assert profile.channel_style_id == "channel_style.casual_host"


def test_channel_style_and_format_apply_independently() -> None:
    genre = genre_registry.get("genre.history")
    investigation_format = format_registry.get("format.investigation")
    channel_style = ChannelStyleProfile(
        channel_style_id="channel_style.casual_host",
        display_name="Casual Host",
        narration_overrides={"narrative_style": "casual_deep_dive"},
    )

    profile = service.compose(
        genre=genre,
        format_profile=investigation_format,
        channel_style=channel_style,
    )

    assert profile.script.narrative_style == "casual_deep_dive"
    assert (
        profile.content_intelligence.narrative_architecture_hint
        == investigation_format.narrative_architecture_hint
    )


def test_audience_passes_through_unmodified() -> None:
    genre = genre_registry.get("genre.travel")
    audience = AudienceProfile(
        audience_id="audience.young_travelers",
        display_name="Young Travelers",
        target_viewer_description="Adults in their 20s planning their next trip.",
    )

    profile = service.compose(genre=genre, audience=audience)

    assert profile.audience is audience
    assert profile.audience_id == "audience.young_travelers"


def test_genre_and_format_schema_versions_are_captured() -> None:
    genre = genre_registry.get("genre.default")
    documentary_format = format_registry.get("format.documentary")

    profile = service.compose(genre=genre, format_profile=documentary_format)

    assert profile.genre_schema_version == genre.schema_version
    assert profile.format_schema_version == documentary_format.schema_version
