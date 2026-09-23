from __future__ import annotations

from src.services.genre_profile_registry_service import (
    GenreProfileRegistryService,
)
from src.services.title_card_text_style_resolution_service import (
    resolve_title_card_text_style,
)


def test_bold_keyword_produces_the_heavy_style() -> None:
    style = resolve_title_card_text_style("bold_mystery")

    assert style.uppercase is True
    assert style.fontsize_scale > 1.0
    assert style.borderw > 3


def test_authoritative_keyword_produces_the_restrained_style() -> None:
    style = resolve_title_card_text_style("authoritative")

    assert style.uppercase is False
    assert style.fontsize_scale < 1.0


def test_clear_authoritative_matches_restrained_via_authoritative_keyword() -> None:
    style = resolve_title_card_text_style("clear_authoritative")

    assert style.uppercase is False
    assert style.fontsize_scale < 1.0


def test_plain_clear_matches_neither_keyword_and_falls_back_to_default() -> None:
    """The model's own field default ("clear") must resolve to the
    plain baseline, not accidentally match a keyword meant for a
    different registered value."""

    style = resolve_title_card_text_style("clear")

    assert style.uppercase is False
    assert style.fontsize_scale == 1.0
    assert style.borderw == 3


def test_an_unrecognized_future_value_never_raises_and_falls_back_to_default() -> None:
    style = resolve_title_card_text_style("something_nobody_has_used_yet")

    assert style.uppercase is False
    assert style.fontsize_scale == 1.0


def test_every_real_registered_genre_text_style_resolves_without_error() -> None:
    """Real, end-to-end confirmation against the actual registry -
    every genre's own text_style must resolve to some real style
    object, never raise."""

    registry = GenreProfileRegistryService.with_default_profiles()

    for profile in registry.list_all():
        style = resolve_title_card_text_style(profile.thumbnail.text_style)

        assert isinstance(style.uppercase, bool)
        assert style.fontsize_scale > 0
        assert style.borderw >= 0
