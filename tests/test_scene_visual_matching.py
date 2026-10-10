"""
Pasting a "narration | on screen" table (2026-10-10, Haunted wife). The table comes from another
assistant and never lines up row for row with the app's scenes (21 rows, 19 scenes: the planner groups
sentences into clips of at most 8 seconds), so rows are matched by their narration text, in order, and
row numbers are ignored. Nothing is guessed: what cannot be found is reported with the nearest scene.
The fixture below is the real table and the real scene narrations of that project.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.scene import Scene
from src.models.scene_visual import (
    SceneVisual,
    SceneVisualPlan,
    narration_key,
    normalize_text,
)
from src.services.scene_visual_matching_service import (
    CROWDED_ROW_COUNT,
    RowStatus,
    SceneVisualMatchingService,
    VisualRow,
)

_SCENES = [
    "He wrote to someone already dead: “What have I done against you?”",
    "The letter was written on papyrus, in Egypt, more than 3,000 years ago. This does not read like a farewell.",
    "It reads like an accusation.",
    "He wrote of her “laying hands on me, even though I committed no wrong against you.”",
    "Her.",
    "The letter names her: the able spirit Ankhiry.",
    "His dead wife.",
    "“Now look, you are disregarding how well I have treated you.”",
    "What exactly she was doing to him, the letter never says. But he believed she was responsible.",
    "He wrote “to make you aware of the things you are doing.”",
    "And Egyptians believed the dead could reach the living.",
    "People had been writing to the dead for more than a thousand years before him.",
    "Was it grief? Guilt? Or did he truly believe his dead wife could still reach him?",
    "His letter survives today, in a museum in the Netherlands.",
    "There is no reply.",
    "We don’t know what happened to him.",
    "We don’t know if it stopped.",
    "Whatever was happening to him, he was certain of one thing:",
    "It was her.",
]

_ROWS = [
    (
        "He wrote to someone already dead: “What have I done against you?”",
        "Extreme close-up of a reed pen on papyrus.",
    ),
    (
        "The letter was written on papyrus, in Egypt, more than 3,000 years ago.",
        "A mud-brick room at night.",
    ),
    (
        "This does not read like a farewell. It reads like an accusation.",
        "His face, half lit, eyes on the doorway.",
    ),
    (
        "He wrote of her “laying hands on me, even though I committed no wrong against you.”",
        "The man asleep; the linen dents.",
    ),
    ("Her.", "Hard cut to black."),
    (
        "The letter names her: the able spirit Ankhiry.",
        "Macro along the papyrus to her name.",
    ),
    ("His dead wife.", "A wrapped body on a bier."),
    (
        "“Now look, you are disregarding how well I have treated you.”",
        "The man at the tomb entrance.",
    ),
    (
        "What exactly she was doing to him, the letter never says.",
        "A water jar rolls across the floor.",
    ),
    ("But he believed she was responsible.", "A tall thin shadow in the corner."),
    (
        "He wrote “to make you aware of the things you are doing.”",
        "His hand pressing the papyrus flat.",
    ),
    (
        "And Egyptians believed the dead could reach the living.",
        "Offering bowls at tomb doors.",
    ),
    (
        "People had been writing to the dead for more than a thousand years before him.",
        "A necropolis under a huge moon.",
    ),
    ("Was it grief? Guilt?", "Close-up of the man, eyes hollow."),
    (
        "Or did he truly believe his dead wife could still reach him?",
        "A pale figure out of focus behind him.",
    ),
    (
        "His letter survives today, in a museum in the Netherlands.",
        "The papyrus under glass in a storeroom.",
    ),
    ("There is no reply.", "Slow push in; one tube flickers off."),
    ("We don’t know what happened to him.", "The empty room from the opening."),
    ("We don’t know if it stopped.", "The reed mat; the linen dents again."),
    (
        "Whatever was happening to him, he was certain of one thing:",
        "The tomb chamber; the torch goes out.",
    ),
    ("It was her.", "A pale outline of a woman’s face for a fraction of a second."),
]


def _scenes(texts: list[str] | None = None) -> list[Scene]:
    return [
        Scene(
            scene_number=i,
            title=f"Scene {i}",
            narration=text,
            visual_prompt="v",
            estimated_duration_seconds=8,
        )
        for i, text in enumerate(texts or _SCENES, start=1)
    ]


def _table(rows: list[tuple[str, str]], *, numbered: bool = True) -> str:
    lines = ["#\tNarration\tOn screen"] if numbered else ["Narration\tOn screen"]

    for i, (narration, visual) in enumerate(rows, start=1):
        lines.append(
            f"{i}\t{narration}\t{visual}" if numbered else f"{narration}\t{visual}"
        )

    return "\n".join(lines)


_SERVICE = SceneVisualMatchingService()


def _match(rows=_ROWS, scenes=None):  # type: ignore[no-untyped-def]
    parsed = _SERVICE.parse(_table(rows))

    return _SERVICE.match(parsed, scenes or _scenes())


# ------------------------------------------------------------------------------ model


def test_normalising_ignores_case_quotes_and_punctuation() -> None:
    assert normalize_text("We don’t know, “really”!") == normalize_text(
        "we don't know really"
    )
    assert narration_key("It was her.") == narration_key("  it WAS her ")
    assert narration_key("It was her.") != narration_key("It was him.")


def test_a_visual_needs_text_and_a_scene() -> None:
    with pytest.raises(ValidationError):
        SceneVisual(scene_number=1, text="", narration_key="k")

    with pytest.raises(ValidationError):
        SceneVisual(scene_number=0, text="x", narration_key="k")


def test_a_visual_is_current_only_for_the_narration_it_was_written_for() -> None:
    scenes = _scenes(["Her.", "His dead wife."])
    plan = SceneVisualPlan(
        visuals=[
            SceneVisual(
                scene_number=1, text="A figure", narration_key=narration_key("Her.")
            )
        ]
    )

    assert plan.current_text_for(1, "Her.") == "A figure"
    assert plan.current_text_for(1, "Him.") == ""
    assert plan.current_text_for(2, "His dead wife.") == ""
    assert plan.current_texts(scenes) == {1: "A figure"}
    assert plan.stale_scene_numbers(scenes) == []

    scenes[0].narration = "Her again."

    assert plan.current_texts(scenes) == {}
    assert plan.stale_scene_numbers(scenes) == [1]


def test_a_visual_for_a_scene_that_no_longer_exists_is_stale() -> None:
    plan = SceneVisualPlan(
        visuals=[SceneVisual(scene_number=5, text="x", narration_key="k")]
    )

    assert plan.stale_scene_numbers(_scenes(["a", "b"])) == [5]


def test_each_saved_plan_gets_its_own_revision() -> None:
    assert SceneVisualPlan().revision != SceneVisualPlan().revision


# ------------------------------------------------------------------------------ parse


def test_a_table_copied_from_chat_parses_and_the_header_is_skipped() -> None:
    rows = _SERVICE.parse(_table(_ROWS))

    assert len(rows) == 21
    assert rows[0].narration.startswith("He wrote to someone already dead")
    assert rows[4] == VisualRow(index=5, narration="Her.", visual="Hard cut to black.")


def test_a_two_column_table_without_numbers_parses() -> None:
    rows = _SERVICE.parse(_table(_ROWS[:3], numbered=False))

    assert [r.narration for r in rows][1].startswith("The letter was written")


def test_a_markdown_pipe_table_parses_and_its_rule_line_is_ignored() -> None:
    text = (
        "| # | Narration | On screen |\n"
        "|---|---|---|\n"
        "| 1 | Her. | A pale shape. |\n"
        "| 2 | His dead wife. | A body on a bier. |\n"
    )

    rows = _SERVICE.parse(text)

    assert [(r.narration, r.visual) for r in rows] == [
        ("Her.", "A pale shape."),
        ("His dead wife.", "A body on a bier."),
    ]


def test_a_visual_that_wrapped_onto_its_own_line_joins_the_row_above() -> None:
    text = "1\tHer.\tA pale shape\ncontinues here\n2\tIt was her.\tA face\n"

    rows = _SERVICE.parse(text)

    assert rows[0].visual == "A pale shape continues here"
    assert len(rows) == 2


def test_rows_with_no_visual_are_skipped_and_markdown_stars_removed() -> None:
    text = "1\tHer.\t-\n2\tIt was her.\t**A face** in the dark\n3\tNo visual\tnone\n"

    rows = _SERVICE.parse(text)

    assert [(r.index, r.narration, r.visual) for r in rows] == [
        (1, "It was her.", "A face in the dark")
    ]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "Paste the table first"),
        ("just a paragraph of words", "with its columns"),
        ("# \tNarration\tOn screen\n", "No row with both"),
    ],
)
def test_text_that_is_not_a_usable_table_is_refused_in_plain_words(
    text: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _SERVICE.parse(text)


# ------------------------------------------------------------------------------ match


def test_the_real_table_places_every_row_in_the_real_scenes() -> None:
    result = _match()

    assert result.unplaced == []
    assert result.scenes_without_visual == []
    placed = result.rows_by_scene()
    assert sorted(placed) == list(range(1, 20))


def test_each_short_repeated_row_lands_in_its_own_scene_by_order() -> None:
    placed = _match().rows_by_scene()

    assert [r.narration for r in placed[5]] == ["Her."]
    assert [r.narration for r in placed[7]] == ["His dead wife."]
    assert [r.narration for r in placed[19]] == ["It was her."]
    assert [r.narration for r in placed[15]] == ["There is no reply."]


def test_two_rows_that_the_planner_joined_into_one_scene_both_go_there() -> None:
    placed = _match().rows_by_scene()

    assert [r.index for r in placed[9]] == [9, 10]
    assert [r.index for r in placed[13]] == [14, 15]


def test_a_row_whose_sentences_fall_in_two_scenes_goes_to_both_and_says_so() -> None:
    result = _match()
    row_three = next(r for r in result.results if r.row.index == 3)

    assert row_three.status == RowStatus.SPANS
    assert row_three.scene_numbers == [2, 3]


def test_scene_two_receives_both_of_its_rows() -> None:
    placed = _match().rows_by_scene()

    assert [r.index for r in placed[2]] == [2, 3]
    assert [r.index for r in placed[3]] == [3]


def test_more_rows_than_scenes_is_fine_because_matching_is_by_text() -> None:
    scenes = _scenes(
        [
            "Was it grief? Guilt? Or did he truly believe his dead wife could still reach him?",
            "His letter survives today, in a museum in the Netherlands. There is no reply.",
        ]
    )
    rows = [
        ("Was it grief? Guilt?", "close-up"),
        ("Or did he truly believe his dead wife could still reach him?", "figure"),
        ("His letter survives today, in a museum in the Netherlands.", "papyrus"),
        ("There is no reply.", "push in"),
    ]

    result = _match(rows, scenes)

    assert result.unplaced == []
    assert {n: len(r) for n, r in result.rows_by_scene().items()} == {1: 2, 2: 2}


def test_a_scene_collecting_many_rows_is_flagged_as_crowded() -> None:
    scenes = _scenes(["One. Two. Three. Four."])
    rows = [(w, f"visual {w}") for w in ("One.", "Two.", "Three.", "Four.")]

    result = _match(rows, scenes)

    assert len(rows) >= CROWDED_ROW_COUNT
    assert result.crowded_scenes == [1]


def test_a_row_that_is_not_in_the_script_is_reported_with_its_nearest_scene() -> None:
    rows = [
        *_ROWS[:3],
        ("The ghost of Ankhiry screamed her name aloud.", "A scream."),
        *_ROWS[3:],
    ]

    result = _match(rows)
    lost = result.unplaced

    assert len(lost) == 1
    assert lost[0].row.visual == "A scream."
    assert lost[0].status == RowStatus.UNMATCHED
    assert lost[0].nearest_scene is not None and lost[0].similarity > 0
    # everything after it still found its scene
    assert 19 in result.rows_by_scene()


def test_a_row_found_only_earlier_in_the_script_is_flagged_out_of_order() -> None:
    rows = [_ROWS[0], _ROWS[3], _ROWS[1]]  # scene 4 before scene 2

    result = _match(rows)
    third = result.results[2]

    assert result.results[1].status == RowStatus.MATCHED
    assert third.status == RowStatus.OUT_OF_ORDER
    assert not third.is_placed


def test_a_row_further_than_the_look_ahead_is_not_dragged_across_the_script() -> None:
    far = [_ROWS[0], ("It was her.", "A face"), _ROWS[1]]

    result = _match(far)

    assert result.results[1].status == RowStatus.UNMATCHED
    assert result.results[2].status == RowStatus.MATCHED
    assert result.results[2].scene_numbers == [2]


def test_an_unplaced_row_can_be_assigned_to_a_scene_by_the_operator() -> None:
    rows = [("A line the script never says.", "A shadow"), *_ROWS[:2]]
    result = _match(rows)

    assert [r.row.index for r in result.unplaced] == [1]

    result.assign(1, 7)

    assert result.unplaced == []
    assert [r.index for r in result.rows_by_scene()[7]] == [1]

    with pytest.raises(ValueError, match="no scene 99"):
        result.assign(1, 99)

    with pytest.raises(ValueError, match="no pasted row 50"):
        result.assign(50, 1)


def test_scenes_with_no_row_are_listed() -> None:
    result = _match(_ROWS[:4])

    assert result.scenes_without_visual[0] == 5
    assert 1 not in result.scenes_without_visual


# ------------------------------------------------------------------------------ plan


def test_the_plan_joins_the_rows_of_a_scene_in_order_and_keys_them_to_the_narration() -> (
    None
):
    result = _match()
    plan = result.to_plan()
    scene_nine = plan.entry_for(9)

    assert scene_nine is not None
    assert scene_nine.text == (
        "A water jar rolls across the floor. Then A tall thin shadow in the corner."
    )
    assert scene_nine.row_count == 2
    assert plan.current_text_for(5, "Her.") == "Hard cut to black."
    assert plan.current_text_for(5, "Something else") == ""
    assert plan.stale_scene_numbers(result.scenes) == []


def test_a_very_long_visual_is_cut_to_the_limit_at_a_word() -> None:
    scenes = _scenes(["Her."])
    result = _match([("Her.", "word " * 600)], scenes)

    entry = result.to_plan().entry_for(1)

    assert entry is not None and len(entry.text) <= 1500
    assert not entry.text.endswith(" ")


# ------------------------------------------------------------- cells on their own lines


def test_a_table_whose_cells_each_sit_on_their_own_line_parses() -> None:
    """Live, 2026-10-10: pasted into a rich-text box, the table's cells read back one per line."""

    text = (
        "\n#\nNarration\nOn screen\n"
        "1\nHer.\nA pale shape\n"
        "2\nIt was her.\nA face in the dark\n"
    )

    rows = _SERVICE.parse(text)

    assert [(r.narration, r.visual) for r in rows] == [
        ("Her.", "A pale shape"),
        ("It was her.", "A face in the dark"),
    ]


def test_a_stacked_visual_that_wraps_over_several_lines_runs_to_the_next_number() -> (
    None
):
    text = (
        "#\nNarration\nOn screen\n"
        "1\nHer.\nA pale shape\nstanding very still\n"
        "2\nIt was her.\nA face\n"
    )

    rows = _SERVICE.parse(text)

    assert rows[0].visual == "A pale shape standing very still"
    assert rows[1].visual == "A face"


def test_the_real_table_parses_the_same_stacked_as_with_tabs() -> None:
    stacked = "#\nNarration\nOn screen\n" + "\n".join(
        f"{i}\n{narration}\n{visual}" for i, (narration, visual) in enumerate(_ROWS, 1)
    )

    assert _SERVICE.parse(stacked) == _SERVICE.parse(_table(_ROWS))


def test_a_two_column_stacked_table_without_numbers_parses() -> None:
    rows = _SERVICE.parse("Narration\nOn screen\nHer.\nA shape\nIt was her.\nA face\n")

    assert [(r.narration, r.visual) for r in rows] == [
        ("Her.", "A shape"),
        ("It was her.", "A face"),
    ]


def test_a_stacked_table_that_does_not_line_up_is_refused_in_plain_words() -> None:
    for broken in (
        "#\nNarration\nOn screen\n1\nHer.\nA shape\n3\nIt was her.\nA face\n",  # skips a number
        "#\nNarration\nOn screen\nHer.\nA shape\n",  # no numbers
        "Narration\nOn screen\nHer.\n",  # odd number of cells
        "#\nNarration\nOn screen\n",  # header only
    ):
        with pytest.raises(ValueError, match="with its columns"):
            _SERVICE.parse(broken)
