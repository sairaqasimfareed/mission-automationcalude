from __future__ import annotations

from src.models.information_reveal_map import (
    CuriosityLoop,
    CuriosityLoopState,
    InformationReveal,
    InformationRevealMap,
)
from src.services.curiosity_loop_validation_service import (
    CuriosityLoopValidationService,
)

service = CuriosityLoopValidationService()


def _map(**overrides: object) -> InformationRevealMap:
    base: dict[str, object] = dict(
        topic="The Mary Celeste",
        curiosity_loops=[
            CuriosityLoop(
                question="Why did the crew vanish?",
                opened_at_position=0.05,
                state=CuriosityLoopState.RESOLVED,
                resolved_at_position=0.9,
            )
        ],
        reveals=[
            InformationReveal(
                position=0.9,
                information="The final theory.",
                is_payoff=True,
                related_question="Why did the crew vanish?",
            )
        ],
        prompt_version="v1",
    )
    base.update(overrides)
    return InformationRevealMap(**base)


def test_a_clean_reveal_map_is_valid() -> None:
    result = service.validate(_map())

    assert result.is_valid is True
    assert result.forgotten_questions == []
    assert result.payoffs_without_setup == []
    assert result.redundant_loops == []
    assert result.prematurely_resolved == []


def test_detects_forgotten_questions() -> None:
    reveal_map = _map(
        curiosity_loops=[
            CuriosityLoop(question="Why did the crew vanish?", opened_at_position=0.05),
        ],
        reveals=[],
    )

    result = service.validate(reveal_map)

    assert result.is_valid is False
    assert result.forgotten_questions == ["Why did the crew vanish?"]


def test_detects_payoff_without_a_matching_loop() -> None:
    reveal_map = _map(
        reveals=[
            InformationReveal(
                position=0.9,
                information="An unrelated payoff.",
                is_payoff=True,
                related_question="A question nobody asked.",
            )
        ],
    )

    result = service.validate(reveal_map)

    assert result.is_valid is False
    assert result.payoffs_without_setup == ["An unrelated payoff."]


def test_payoff_with_no_related_question_at_all_is_flagged() -> None:
    reveal_map = _map(
        reveals=[
            InformationReveal(
                position=0.9,
                information="A dangling payoff.",
                is_payoff=True,
            )
        ],
    )

    result = service.validate(reveal_map)

    assert result.payoffs_without_setup == ["A dangling payoff."]


def test_non_payoff_reveals_are_never_flagged() -> None:
    reveal_map = _map(
        reveals=[
            InformationReveal(
                position=0.5,
                information="Just a fact, not a payoff.",
                is_payoff=False,
            )
        ],
    )

    result = service.validate(reveal_map)

    assert result.payoffs_without_setup == []


def test_detects_redundant_loops_case_and_whitespace_insensitively() -> None:
    reveal_map = _map(
        curiosity_loops=[
            CuriosityLoop(question="Why did the crew vanish?", opened_at_position=0.05),
            CuriosityLoop(
                question="  why did the CREW vanish?  ", opened_at_position=0.1
            ),
        ],
        reveals=[],
    )

    result = service.validate(reveal_map)

    assert result.is_valid is False
    assert len(result.redundant_loops) == 1


def test_detects_premature_resolution() -> None:
    reveal_map = _map(
        curiosity_loops=[
            CuriosityLoop(
                question="Why did the crew vanish?",
                opened_at_position=0.0,
                state=CuriosityLoopState.RESOLVED,
                resolved_at_position=0.05,
            )
        ],
    )

    result = service.validate(reveal_map)

    assert result.is_valid is False
    assert result.prematurely_resolved == ["Why did the crew vanish?"]


def test_premature_resolution_is_allowed_when_flagged() -> None:
    reveal_map = _map(
        curiosity_loops=[
            CuriosityLoop(
                question="Why did the crew vanish?",
                opened_at_position=0.0,
                state=CuriosityLoopState.RESOLVED,
                resolved_at_position=0.05,
                allow_early_resolution=True,
            )
        ],
    )

    result = service.validate(reveal_map)

    assert result.prematurely_resolved == []
