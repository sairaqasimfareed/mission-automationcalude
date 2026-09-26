from __future__ import annotations

from src.models.caption_style_option import CaptionStyleOption
from src.models.effect_registry import EffectCategory
from src.services.effect_registry_service import EffectRegistryService
from src.services.genre_profile_registry_service import GenreProfileRegistryService
from src.services.video_filter_translation_service import (
    VideoFilterTranslationService,
)

_FALLBACK_PRESET_ID = "subtitle.default"


class CaptionStyleOptionsService:
    """
    Real, selectable caption styles for the manual override picker
    (Project settings' "Caption style" card) - one CaptionStyleOption
    per registered subtitle.* preset in EffectRegistryService, each
    carrying VideoFilterTranslationService's own real FFmpeg style
    dict for that preset, so a GUI preview can never drift from what a
    real render actually burns in. Never a second, GUI-only style
    catalog (AGENTS.md rule 2).
    """

    def __init__(
        self,
        *,
        effect_registry: EffectRegistryService | None = None,
        genre_registry: GenreProfileRegistryService | None = None,
    ) -> None:
        self._effect_registry = (
            effect_registry or EffectRegistryService.with_default_presets()
        )
        self._genre_registry = (
            genre_registry or GenreProfileRegistryService.with_default_profiles()
        )

    def list_options(self, *, genre_id: str) -> list[CaptionStyleOption]:
        """
        Every real, active subtitle preset, marking whichever one this
        genre would pick automatically. GenreEditingProfile.
        subtitle_preset_id is one fixed value per genre (never
        scene-varying - confirmed via GenreDirectiveGenerationService,
        which only varies camera/effect intensity per scene, never
        subtitle style), so this is a single project-wide "Auto" value,
        not a per-scene one.
        """

        genre_default_preset_id = self._resolve_genre_default_preset_id(genre_id)

        presets = self._effect_registry.list_by_category(
            EffectCategory.SUBTITLE,
            active_only=True,
        )

        return [
            CaptionStyleOption(
                preset_id=preset.preset_id,
                display_name=preset.display_name,
                is_genre_default=(preset.preset_id == genre_default_preset_id),
                style=VideoFilterTranslationService._subtitle_style(preset.preset_id),
            )
            for preset in presets
        ]

    def _resolve_genre_default_preset_id(self, genre_id: str) -> str:
        resolution = self._genre_registry.resolve(genre_id, allow_fallback=True)

        if not resolution.is_resolved or resolution.profile is None:
            return _FALLBACK_PRESET_ID

        return resolution.profile.editing.subtitle_preset_id
