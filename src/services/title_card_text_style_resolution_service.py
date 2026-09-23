from __future__ import annotations

from src.models.title_card_text_style import TitleCardTextStyle

# REQ-4 (opening title card), 2026-09-22: real, registered
# GenreEditingProfile.text_style values are free-form strings, not a
# fixed enum (confirmed via grep across genre_profile_registry_
# service.py: "bold_mystery", "authoritative", "bold_historical",
# "destination_bold", "large_number", "story_hook",
# "clear_authoritative", "bold_expressive", "bold_survival",
# "bold_playful", model default "clear") - classified here by
# substring keyword rather than an exhaustive lookup table, so a
# future genre's own new text_style value degrades to a sensible
# default instead of raising.
_HEAVY_KEYWORDS = ("bold", "large", "expressive", "playful")
_RESTRAINED_KEYWORDS = ("authoritative", "hook")

_HEAVY_STYLE = TitleCardTextStyle(uppercase=True, fontsize_scale=1.15, borderw=6)
_RESTRAINED_STYLE = TitleCardTextStyle(uppercase=False, fontsize_scale=0.95, borderw=3)
_DEFAULT_STYLE = TitleCardTextStyle(uppercase=False, fontsize_scale=1.0, borderw=3)


def resolve_title_card_text_style(text_style: str) -> TitleCardTextStyle:
    """
    REQ-4 (opening title card): map a genre's own
    GenreEditingProfile.text_style string to a real, drawtext-
    realizable text treatment for the title beat.

    Heavy keywords ("bold"/"large"/"expressive"/"playful") checked
    first since most real registered values contain "bold" as a
    substring - the dominant real-world case (horror, history, travel,
    reaction, survival, comedy). Restrained keywords ("authoritative"/
    "clear"/"hook") cover documentary/medical/storytelling. Anything
    matching neither (a genre's default "clear" case, or a future,
    unclassified value) falls back to the same baseline "clear" would
    produce - never raises.
    """

    normalized = text_style.lower()

    if any(keyword in normalized for keyword in _HEAVY_KEYWORDS):
        return _HEAVY_STYLE

    if any(keyword in normalized for keyword in _RESTRAINED_KEYWORDS):
        return _RESTRAINED_STYLE

    return _DEFAULT_STYLE
