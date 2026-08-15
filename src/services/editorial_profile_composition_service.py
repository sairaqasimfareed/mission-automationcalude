from __future__ import annotations

from src.models.editorial_profile import (
    AudienceProfile,
    ChannelStyleProfile,
    EditorialProfile,
    FormatProfile,
)
from src.models.genre_profile import (
    GenreContentIntelligenceProfile,
    GenreProfile,
    GenreScriptProfile,
)


class EditorialProfileCompositionService:
    """
    Pure-function composition of genre + format + audience + channel
    style into one resolved EditorialProfile.

    Deterministic precedence, most specific wins: channel_style
    overrides format overrides genre - and only for fields the more
    specific profile actually set (sparse override), never a full
    replacement. This resolves contradictions mechanically (e.g.
    channel style says conversational narration, genre says
    authoritative narration -> channel wins) instead of asking an LLM
    to guess which instruction matters more.
    """

    def compose(
        self,
        *,
        genre: GenreProfile,
        format_profile: FormatProfile | None = None,
        audience: AudienceProfile | None = None,
        channel_style: ChannelStyleProfile | None = None,
    ) -> EditorialProfile:
        """Merge genre with optional format/audience/channel-style overrides."""

        content_intelligence = self._apply_format_overrides(
            genre.content_intelligence, format_profile
        )
        script = self._apply_channel_overrides(genre.script, channel_style)

        return EditorialProfile(
            genre_id=genre.genre_id,
            format_id=format_profile.format_id if format_profile else None,
            audience_id=audience.audience_id if audience else None,
            channel_style_id=(
                channel_style.channel_style_id if channel_style else None
            ),
            genre_schema_version=genre.schema_version,
            format_schema_version=(
                format_profile.schema_version if format_profile else None
            ),
            script=script,
            content_intelligence=content_intelligence,
            audience=audience,
            beat_type_bias=(
                list(format_profile.beat_type_bias) if format_profile else []
            ),
        )

    @staticmethod
    def _apply_format_overrides(
        content_intelligence: GenreContentIntelligenceProfile,
        format_profile: FormatProfile | None,
    ) -> GenreContentIntelligenceProfile:
        if format_profile is None:
            return content_intelligence

        updates: dict[str, object] = {}

        if format_profile.narrative_architecture_hint:
            updates["narrative_architecture_hint"] = (
                format_profile.narrative_architecture_hint
            )

        if format_profile.pacing_curve_override:
            updates["pacing_curve"] = format_profile.pacing_curve_override

        if format_profile.scene_density_multiplier != 1.0:
            updates["scene_density_per_minute"] = (
                content_intelligence.scene_density_per_minute
                * format_profile.scene_density_multiplier
            )

        if not updates:
            return content_intelligence

        return content_intelligence.model_copy(update=updates)

    @staticmethod
    def _apply_channel_overrides(
        script: GenreScriptProfile,
        channel_style: ChannelStyleProfile | None,
    ) -> GenreScriptProfile:
        if channel_style is None or not channel_style.narration_overrides:
            return script

        # ChannelStyleProfile.narration_overrides is already validated
        # to only contain plain free-text GenreScriptProfile field
        # names (see _OVERRIDABLE_NARRATION_FIELDS), so this update is
        # guaranteed not to write an invalid value into an enum field.
        updates: dict[str, object] = dict(channel_style.narration_overrides)

        return script.model_copy(update=updates)
