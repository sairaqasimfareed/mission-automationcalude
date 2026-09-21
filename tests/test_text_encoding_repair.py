from __future__ import annotations

from src.shared.text_encoding_repair import repair_mojibake, repair_mojibake_deep


def _corrupted_em_dash_text() -> str:
    """
    The exact corruption signature confirmed on a real job: a UTF-8
    em dash decoded as cp1252 becomes three separate characters
    (U+00E2, U+20AC, U+201D) instead of one (U+2014).
    """

    return b"cunning \xc3\xa2\xe2\x82\xac\xe2\x80\x9d but it wasn't.".decode("utf-8")


def test_repairs_the_confirmed_em_dash_corruption() -> None:
    repaired = repair_mojibake(_corrupted_em_dash_text())

    assert repaired == "cunning — but it wasn't."


def test_leaves_clean_text_unchanged() -> None:
    clean = "It looked like cunning — but it wasn't."

    assert repair_mojibake(clean) == clean


def test_leaves_plain_ascii_text_unchanged() -> None:
    plain = "A truck-mounted gun failed on rough terrain."

    assert repair_mojibake(plain) == plain


def test_leaves_text_without_the_marker_character_unchanged() -> None:
    # Contains non-ASCII text but never the U+00E2 marker this
    # detector keys off - must not be touched.
    text = "Café society in 1930s Paris."

    assert repair_mojibake(text) == text


def test_deep_repairs_nested_dict_and_list_values() -> None:
    payload = {
        "narration": _corrupted_em_dash_text(),
        "beats": [
            {"summary": _corrupted_em_dash_text()},
            {"summary": "already clean"},
        ],
        "scene_number": 6,
    }

    repaired = repair_mojibake_deep(payload)

    assert repaired["narration"] == "cunning — but it wasn't."
    assert repaired["beats"][0]["summary"] == "cunning — but it wasn't."
    assert repaired["beats"][1]["summary"] == "already clean"
    assert repaired["scene_number"] == 6
