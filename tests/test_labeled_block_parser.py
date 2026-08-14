from __future__ import annotations

from src.services.llm.labeled_block_parser import extract_labeled_field


def test_extracts_a_simple_labeled_field() -> None:
    content = "TITLE: The Missing Logbook\nBODY: Something else."

    assert extract_labeled_field(content, "TITLE") == "The Missing Logbook"


def test_is_case_insensitive() -> None:
    content = "title: lowercase label"

    assert extract_labeled_field(content, "TITLE") == "lowercase label"


def test_tolerates_extra_whitespace_around_colon() -> None:
    content = "TITLE   :   padded value  "

    assert extract_labeled_field(content, "TITLE") == "padded value"


def test_returns_none_when_label_is_missing() -> None:
    content = "BODY: no title here"

    assert extract_labeled_field(content, "TITLE") is None


def test_returns_none_for_an_empty_value() -> None:
    content = "TITLE:   \nBODY: something"

    assert extract_labeled_field(content, "TITLE") is None


def test_finds_label_anywhere_in_a_multiline_block() -> None:
    content = (
        "CONCEPT: A diver facing a giant squid.\n"
        "HOOK: GIANT SQUID ATTACK\n"
        "PROMPT: A dramatic underwater scene."
    )

    assert extract_labeled_field(content, "HOOK") == "GIANT SQUID ATTACK"


def test_does_not_match_a_label_that_is_a_substring_of_another() -> None:
    content = "SUBTITLE: not the title\nTITLE: the real title"

    assert extract_labeled_field(content, "TITLE") == "the real title"
