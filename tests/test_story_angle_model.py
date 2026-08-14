from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.story_angle import (
    FACTUAL_SUPPORT_FLOOR,
    StoryAngle,
    StoryAngleEvaluation,
    StoryAngleStyle,
)


def test_valid_angle_constructs() -> None:
    angle = StoryAngle(
        style=StoryAngleStyle.MYSTERY,
        title="The Missing Logbook",
        description="Told through the lens of the ship's missing final log entry.",
    )

    assert angle.style == StoryAngleStyle.MYSTERY


def test_angle_rejects_empty_title() -> None:
    with pytest.raises(ValidationError):
        StoryAngle(
            style=StoryAngleStyle.MYSTERY,
            title="   ",
            description="Something.",
        )


def _evaluation(**overrides: object) -> StoryAngleEvaluation:
    base: dict[str, object] = dict(
        angle_title="The Missing Logbook",
        hook_potential=80,
        curiosity=85,
        emotional_impact=70,
        originality=75,
        factual_support=90,
        clarity=80,
        tension=75,
        audience_fit=85,
        visual_potential=70,
        audio_potential=65,
        production_feasibility=80,
        payoff_potential=85,
        retention_potential=80,
        reasoning="Strong factual grounding and a clear unanswered question.",
    )
    base.update(overrides)
    return StoryAngleEvaluation(**base)


def test_overall_score_is_the_mean_of_all_dimensions_when_factual_support_is_high() -> (
    None
):
    evaluation = _evaluation()

    dimensions = (
        evaluation.hook_potential,
        evaluation.curiosity,
        evaluation.emotional_impact,
        evaluation.originality,
        evaluation.factual_support,
        evaluation.clarity,
        evaluation.tension,
        evaluation.audience_fit,
        evaluation.visual_potential,
        evaluation.audio_potential,
        evaluation.production_feasibility,
        evaluation.payoff_potential,
        evaluation.retention_potential,
    )

    assert evaluation.overall_score == pytest.approx(sum(dimensions) / len(dimensions))


def test_low_factual_support_caps_overall_score() -> None:
    """
    Spec section 22: factual integrity must override engagement
    optimization. An angle with maxed-out engagement dimensions but
    weak factual support must not be able to outrank a factually
    solid, merely-good angle.
    """

    weak_factual_but_flashy = _evaluation(
        hook_potential=100,
        curiosity=100,
        emotional_impact=100,
        originality=100,
        factual_support=20,
        clarity=100,
        tension=100,
        audience_fit=100,
        visual_potential=100,
        audio_potential=100,
        production_feasibility=100,
        payoff_potential=100,
        retention_potential=100,
    )

    assert weak_factual_but_flashy.factual_support < FACTUAL_SUPPORT_FLOOR
    assert weak_factual_but_flashy.overall_score == 20.0

    solid_but_unremarkable = _evaluation(
        hook_potential=60,
        curiosity=60,
        emotional_impact=60,
        originality=60,
        factual_support=60,
        clarity=60,
        tension=60,
        audience_fit=60,
        visual_potential=60,
        audio_potential=60,
        production_feasibility=60,
        payoff_potential=60,
        retention_potential=60,
    )

    assert solid_but_unremarkable.overall_score > weak_factual_but_flashy.overall_score


def test_confidence_score_is_overall_score_normalized() -> None:
    evaluation = _evaluation()

    assert evaluation.confidence_score == pytest.approx(
        evaluation.overall_score / 100.0
    )


def test_score_dimensions_reject_out_of_range_values() -> None:
    with pytest.raises(ValidationError):
        _evaluation(hook_potential=101)

    with pytest.raises(ValidationError):
        _evaluation(curiosity=-1)
