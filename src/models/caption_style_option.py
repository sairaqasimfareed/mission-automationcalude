from __future__ import annotations

from pydantic import Field

from src.models.base import MissionBaseModel


class CaptionStyleOption(MissionBaseModel):
    """
    One selectable caption style for the manual override picker
    (Project settings' "Caption style" card).

    preset_id/display_name come straight from EffectRegistryService's
    own registered subtitle.* presets - never a second, GUI-only
    catalog. style is VideoFilterTranslationService._subtitle_style()'s
    own real FFmpeg style dict (fontcolor/fontsize/borderw/bordercolor)
    for this exact preset_id, so a GUI preview built from it can never
    drift from what a real render actually burns in. is_genre_default
    marks whichever preset the current job's genre would pick
    automatically (GenreEditingProfile.subtitle_preset_id), so an
    override is always made with visibility of what Auto already
    selected.
    """

    preset_id: str
    display_name: str
    is_genre_default: bool = False
    style: dict[str, str] = Field(default_factory=dict)
