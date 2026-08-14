from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.information_reveal_map import (
    CuriosityLoop,
    CuriosityLoopState,
    InformationReveal,
    InformationRevealMap,
)


def test_valid_loop_constructs() -> None:
    loop = CuriosityLoop(question="Why did the crew vanish?", opened_at_position=0.05)

    assert loop.state == CuriosityLoopState.OPEN
    assert loop.resolved_at_position is None


def test_loop_rejects_empty_question() -> None:
    with pytest.raises(ValidationError):
        CuriosityLoop(question="   ", opened_at_position=0.0)


def test_loop_cannot_resolve_before_it_opens() -> None:
    with pytest.raises(ValidationError, match="cannot resolve before it opens"):
        CuriosityLoop(
            question="Why?",
            opened_at_position=0.5,
            resolved_at_position=0.1,
        )


def test_resolved_state_requires_resolved_at_position() -> None:
    with pytest.raises(ValidationError, match="requires resolved_at_position"):
        CuriosityLoop(
            question="Why?",
            opened_at_position=0.1,
            state=CuriosityLoopState.RESOLVED,
        )


def test_resolved_loop_with_position_is_valid() -> None:
    loop = CuriosityLoop(
        question="Why?",
        opened_at_position=0.1,
        state=CuriosityLoopState.RESOLVED,
        resolved_at_position=0.9,
    )

    assert loop.resolved_at_position == 0.9


def test_reveal_rejects_empty_information() -> None:
    with pytest.raises(ValidationError):
        InformationReveal(position=0.5, information="   ")


def test_reveal_related_question_none_when_blank() -> None:
    reveal = InformationReveal(
        position=0.5, information="A clue.", related_question="  "
    )

    assert reveal.related_question is None


def test_reveal_map_requires_at_least_one_loop() -> None:
    with pytest.raises(ValidationError, match="at least one"):
        InformationRevealMap(
            topic="The Mary Celeste",
            curiosity_loops=[],
            reveals=[],
            prompt_version="v1",
        )


def test_reveal_map_constructs_with_loops_and_reveals() -> None:
    reveal_map = InformationRevealMap(
        topic="The Mary Celeste",
        curiosity_loops=[
            CuriosityLoop(question="Why did the crew vanish?", opened_at_position=0.05)
        ],
        reveals=[InformationReveal(position=0.9, information="The final theory.")],
        prompt_version="v1",
    )

    assert len(reveal_map.curiosity_loops) == 1
    assert len(reveal_map.reveals) == 1
