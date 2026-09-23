from __future__ import annotations

from src.services.title_card_text_resolution_service import (
    resolve_title_card_text,
)


def test_manual_override_wins_unconditionally() -> None:
    result = resolve_title_card_text(
        override="My Manual Title",
        selected_seo_title="SEO Title",
        topic="Raw topic seed",
    )

    assert result == "My Manual Title"


def test_falls_back_to_selected_seo_title_when_no_override() -> None:
    result = resolve_title_card_text(
        override=None,
        selected_seo_title="SEO Title",
        topic="Raw topic seed",
    )

    assert result == "SEO Title"


def test_falls_back_to_topic_when_neither_override_nor_seo_title_exist() -> None:
    result = resolve_title_card_text(
        override=None,
        selected_seo_title=None,
        topic="Raw topic seed",
    )

    assert result == "Raw topic seed"


def test_blank_override_falls_through_to_seo_title() -> None:
    result = resolve_title_card_text(
        override="   ",
        selected_seo_title="SEO Title",
        topic="Raw topic seed",
    )

    assert result == "SEO Title"


def test_blank_selected_seo_title_falls_through_to_topic() -> None:
    result = resolve_title_card_text(
        override=None,
        selected_seo_title="",
        topic="Raw topic seed",
    )

    assert result == "Raw topic seed"


def test_result_is_stripped_of_surrounding_whitespace() -> None:
    result = resolve_title_card_text(
        override="  Padded Title  ",
        selected_seo_title=None,
        topic="Raw topic seed",
    )

    assert result == "Padded Title"
