"""
Character-Oriented Video mode, step 1 (2026-10-09): the operator's own `NAME: line` script is read
into attributed lines, one list per scene. Strict on purpose - a line with no speaker is an error
that names its line, never a continuation of the line above, because the clip is lip-synced to whoever
the prompt says is speaking.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.dialogue import DialogueLine, speakers_in, spoken_text
from src.models.generated_script import GeneratedScript, ScriptSegment
from src.models.scene import Scene
from src.models.story_blueprint import StoryBeatType
from src.services.dialogue_script_parser import (
    DialogueScriptError,
    parse_dialogue_script,
    speakers_of,
)

_SCRIPT = """WALTER: Postmaster says the afternoon train is late again.

WALTER: We cannot hold the post past six.
FRANK: Then you had better start sorting.
"""


# ---------------------------------------------------------------------------- model


def test_a_line_cleans_its_name_and_words() -> None:
    line = DialogueLine(speaker="  Walter   Hale ", text=" We  cannot hold   it. ")

    assert (line.speaker, line.text) == ("Walter Hale", "We cannot hold it.")
    assert line.word_count == 4


def test_a_line_needs_a_speaker_and_words() -> None:
    with pytest.raises(ValidationError):
        DialogueLine(speaker="", text="Hello")

    with pytest.raises(ValidationError):
        DialogueLine(speaker="Walter", text="")


def test_the_spoken_text_is_the_words_without_the_names() -> None:
    lines = [
        DialogueLine(speaker="A", text="One."),
        DialogueLine(speaker="B", text="Two."),
    ]

    assert spoken_text(lines) == "One. Two."


def test_speakers_are_listed_once_in_order_of_first_appearance() -> None:
    lines = [
        DialogueLine(speaker="B", text="x"),
        DialogueLine(speaker="A", text="y"),
        DialogueLine(speaker="B", text="z"),
    ]

    assert speakers_in(lines) == ["B", "A"]


# --------------------------------------------------------------------------- parser


def test_blank_lines_separate_scenes_and_each_line_has_its_speaker() -> None:
    scenes = parse_dialogue_script(_SCRIPT)

    assert [[(line.speaker, line.text) for line in scene] for scene in scenes] == [
        [("Walter", "Postmaster says the afternoon train is late again.")],
        [
            ("Walter", "We cannot hold the post past six."),
            ("Frank", "Then you had better start sorting."),
        ],
    ]


def test_speakers_of_a_script_are_listed_once() -> None:
    assert speakers_of(parse_dialogue_script(_SCRIPT)) == ["Walter", "Frank"]


def test_quotation_marks_around_the_words_are_dropped() -> None:
    scenes = parse_dialogue_script('WALTER: "We cannot hold the post."\nFRANK: “No.”')

    assert [line.text for line in scenes[0]] == ["We cannot hold the post.", "No."]


def test_quotes_inside_the_words_are_kept() -> None:
    scenes = parse_dialogue_script('WALTER: He said "late" again.')

    assert scenes[0][0].text == 'He said "late" again.'


def test_all_caps_names_become_ordinary_names_and_one_person_stays_one_person() -> None:
    scenes = parse_dialogue_script(
        "WALTER HALE: One.\nwalter hale: Two.\nFRANK DOYLE: Three."
    )

    assert [line.speaker for scene in scenes for line in scene] == [
        "Walter Hale",
        "Walter Hale",
        "Frank Doyle",
    ]


def test_the_first_spelling_of_a_name_is_kept() -> None:
    scenes = parse_dialogue_script("Walter: One.\nWALTER: Two.")

    assert {line.speaker for line in scenes[0]} == {"Walter"}


def test_a_name_with_a_title_and_a_period_is_a_name() -> None:
    scenes = parse_dialogue_script("Dr. Hale: Sit down.")

    assert scenes[0][0].speaker == "Dr. Hale"


def test_windows_line_endings_and_extra_blank_lines_are_fine() -> None:
    scenes = parse_dialogue_script("A: One.\r\n\r\n\r\nB: Two.\r\n")

    assert [len(scene) for scene in scenes] == [1, 1]


def test_a_colon_inside_the_words_stays_in_the_words() -> None:
    scenes = parse_dialogue_script("Walter: Remember this: six o'clock.")

    assert scenes[0][0].text == "Remember this: six o'clock."


def test_a_line_with_no_speaker_is_an_error_naming_its_line() -> None:
    with pytest.raises(DialogueScriptError, match="Line 2 has no speaker"):
        parse_dialogue_script("WALTER: One.\nand then he left")


def test_a_wrapped_line_is_not_glued_to_the_line_above() -> None:
    with pytest.raises(DialogueScriptError, match="Line 2"):
        parse_dialogue_script("WALTER: We cannot hold\nthe post past six.")


def test_a_sentence_before_a_colon_is_not_taken_for_a_speaker() -> None:
    with pytest.raises(DialogueScriptError, match="no speaker"):
        parse_dialogue_script("It was the longest night of the whole year: he left.")


def test_a_speaker_with_no_words_is_an_error() -> None:
    with pytest.raises(DialogueScriptError, match="no speaker|no words"):
        parse_dialogue_script("WALTER:")


def test_an_empty_script_is_an_error() -> None:
    with pytest.raises(DialogueScriptError, match="empty"):
        parse_dialogue_script("  \n\n ")


def test_a_very_long_speaker_name_is_refused() -> None:
    with pytest.raises(DialogueScriptError):
        parse_dialogue_script("a b c d e f g: words")


# ----------------------------------------------------------- the segment and scene


def _segment(dialogue: list[DialogueLine]) -> ScriptSegment:
    return ScriptSegment(
        segment_number=1,
        start_seconds=0.0,
        end_seconds=8.0,
        narrative_function=StoryBeatType.HOOK,
        narration=spoken_text(dialogue) or "Narration.",
        tension_level=30,
        dialogue=dialogue,
    )


def test_a_segment_and_a_scene_carry_their_dialogue() -> None:
    lines = [DialogueLine(speaker="Walter", text="We cannot hold the post.")]
    scene = Scene(
        scene_number=1,
        title="One",
        narration=spoken_text(lines),
        visual_prompt="v",
        estimated_duration_seconds=8,
        dialogue=lines,
    )

    assert _segment(lines).dialogue[0].speaker == "Walter"
    assert scene.dialogue[0].text == "We cannot hold the post."


def test_old_segments_and_scenes_load_without_dialogue() -> None:
    segment_data = _segment([]).model_dump(mode="json")
    segment_data.pop("dialogue")
    scene_data = Scene(
        scene_number=1,
        title="One",
        narration="n",
        visual_prompt="v",
        estimated_duration_seconds=8,
    ).model_dump(mode="json")
    scene_data.pop("dialogue")

    assert ScriptSegment.model_validate(segment_data).dialogue == []
    assert Scene.model_validate(scene_data).dialogue == []


def _script(dialogue: list[DialogueLine]) -> GeneratedScript:
    return GeneratedScript(
        topic="Post office",
        genre_id="genre.history",
        target_duration_seconds=60,
        segments=[_segment(dialogue)],
        prompt_version="v1",
    )


def test_a_script_without_dialogue_hashes_exactly_as_before() -> None:
    plain = _script([])
    explicit = _script([])

    assert plain.content_hash == explicit.content_hash
    assert "|" not in "".join(
        line.speaker for s in plain.segments for line in s.dialogue
    )


def test_changing_only_who_speaks_changes_the_script_hash() -> None:
    by_walter = _script([DialogueLine(speaker="Walter", text="Same words.")])
    by_frank = _script([DialogueLine(speaker="Frank", text="Same words.")])

    assert by_walter.segments[0].narration == by_frank.segments[0].narration
    assert by_walter.content_hash != by_frank.content_hash
