from __future__ import annotations

from src.services.llm.labeled_block_parser import extract_labeled_field, split_blocks


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


def test_split_blocks_separates_on_dash_lines() -> None:
    content = "TITLE: One\n---\nTITLE: Two\n----\nTITLE: Three"

    blocks = split_blocks(content)

    assert len(blocks) == 3
    assert extract_labeled_field(blocks[0], "TITLE") == "One"
    assert extract_labeled_field(blocks[1], "TITLE") == "Two"
    assert extract_labeled_field(blocks[2], "TITLE") == "Three"


def test_split_blocks_returns_one_block_when_no_separator_present() -> None:
    blocks = split_blocks("TITLE: Only one block")

    assert len(blocks) == 1


def test_split_blocks_strips_surrounding_whitespace() -> None:
    blocks = split_blocks("\n\n  TITLE: Only one block  \n\n")

    assert blocks == ["TITLE: Only one block"]
