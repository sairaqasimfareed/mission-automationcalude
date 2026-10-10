"""
Character-Oriented Video mode, step 6 (2026-10-09): how much the characters have to say against how long
the clip is. On camera a person speaks at most about 2.5 words a second; more than the clip can carry
makes the provider rush the speech (live: two lines written for about 9.6 s were squeezed into 8 s and
both voices ran at roughly 3.5-3.9 words a second). It measures and reports; it never rewrites.
"""

from __future__ import annotations

from src.models.dialogue import DialogueLine
from src.models.scene import Scene
from src.services.speech_budget import (
    MAX_WORDS_PER_SECOND,
    speech_budget,
    speech_budget_message,
)


def _scene(words: int, *, planned_seconds: int = 8, speakers: int = 1) -> Scene:
    per = max(1, words // speakers)
    lines = [
        DialogueLine(speaker=f"P{n}", text=" ".join(["word"] * per))
        for n in range(speakers)
    ]

    return Scene(
        scene_number=1,
        title="One",
        narration=" ".join(line.text for line in lines),
        visual_prompt="v",
        estimated_duration_seconds=planned_seconds,
        dialogue=lines,
    )


def test_a_narrated_scene_has_no_budget() -> None:
    scene = Scene(
        scene_number=1,
        title="One",
        narration="n",
        visual_prompt="v",
        estimated_duration_seconds=8,
    )

    assert speech_budget(scene, max_clip_seconds=10) is None


def test_a_line_that_fits_is_within_budget() -> None:
    budget = speech_budget(_scene(15, planned_seconds=8), max_clip_seconds=10)

    assert budget is not None and budget.over is False
    assert budget.allowed_words == 20
    assert round(budget.words_per_second, 2) == 1.88


def test_a_line_over_two_and_a_half_words_a_second_is_over_budget() -> None:
    budget = speech_budget(_scene(30, planned_seconds=8), max_clip_seconds=10)

    assert budget is not None and budget.over is True


def test_exactly_the_limit_is_allowed() -> None:
    budget = speech_budget(_scene(20, planned_seconds=8), max_clip_seconds=10)

    assert budget is not None and budget.over is False
    assert MAX_WORDS_PER_SECOND == 2.5


def test_the_clip_is_capped_at_the_providers_longest_clip() -> None:
    long_plan = _scene(40, planned_seconds=16)

    muse = speech_budget(long_plan, max_clip_seconds=10)
    flow = speech_budget(long_plan, max_clip_seconds=8)

    assert muse is not None and flow is not None
    assert muse.clip_seconds == 10 and muse.allowed_words == 25 and muse.over is True
    assert flow.clip_seconds == 8 and flow.allowed_words == 20 and flow.over is True


def test_the_words_of_every_line_in_a_two_person_scene_are_counted() -> None:
    budget = speech_budget(
        _scene(24, planned_seconds=8, speakers=2), max_clip_seconds=10
    )

    assert budget is not None and budget.words == 24 and budget.over is True


def test_the_message_says_what_is_wrong_and_what_to_do() -> None:
    budget = speech_budget(_scene(30, planned_seconds=8), max_clip_seconds=10)
    assert budget is not None

    message = speech_budget_message(budget)

    assert "30 words of dialogue for a 8 s clip" in message
    assert "rushed" in message and "split the exchange" in message
