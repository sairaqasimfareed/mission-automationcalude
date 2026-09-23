from __future__ import annotations

from src.models.base import MissionBaseModel


class TitleCardTextStyle(MissionBaseModel):
    """
    REQ-4 (opening title card): one real, FFmpeg-drawtext-realizable
    text treatment.

    Deliberately limited to fields drawtext actually supports -
    letter-spacing, italics, and true font-weight variants are NOT
    real drawtext capabilities without a second font FILE (this
    codebase has exactly one system font resolved per platform, no
    per-weight font library - see VideoFilterTranslationService.
    _resolve_subtitle_font_file()). "Heavier"/"punchier" is
    approximated honestly within what drawtext can do: uppercase text,
    a larger relative size, and a thicker outline read as bolder even
    on the one available font.
    """

    uppercase: bool = False

    fontsize_scale: float = 1.0

    borderw: int = 3
