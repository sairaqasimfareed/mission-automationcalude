from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.hook import FACTUAL_SUPPORT_FLOOR, HookCandidate, HookEvaluation


def test_valid_candidate_constructs() -> None:
    candidate = HookCandidate(text="The crew vanished without a trace.")

    assert candidate.text == "The crew vanished without a trace."


def test_candidate_rejects_empty_text() -> None:
    with pytest.raises(ValidationError):
        HookCandidate(text="   ")


def _evaluation(**overrides: object) -> HookEvaluation:
    base: dict[str, object] = dict(
        hook_text="The crew vanished without a trace.",
        immediate_curiosity=85,
        specificity=80,
        stakes=75,
        clarity=80,
        emotional_impact=70,
        novelty=75,
        relevance=85,
        audience_fit=80,
        factual_support=90,
        spoiler_risk=10,
        rejected=False,
        reasoning="Strong, specific hook grounded in verified facts.",
    )
    base.update(overrides)
    return HookEvaluation(**base)


def test_overall_score_penalizes_spoiler_risk() -> None:
    low_risk = _evaluation(spoiler_risk=0)
    high_risk = _evaluation(spoiler_risk=80)

    assert low_risk.overall_score > high_risk.overall_score


def test_rejected_hook_always_scores_zero() -> None:
    evaluation = _evaluation(
        rejected=True,
        immediate_curiosity=100,
        specificity=100,
        stakes=100,
        clarity=100,
        emotional_impact=100,
        novelty=100,
        relevance=100,
        audience_fit=100,
        factual_support=100,
        spoiler_risk=0,
    )

    assert evaluation.overall_score == 0.0


def test_low_factual_support_caps_overall_score() -> None:
    evaluation = _evaluation(
        immediate_curiosity=100,
        specificity=100,
        stakes=100,
        clarity=100,
        emotional_impact=100,
        novelty=100,
        relevance=100,
        audience_fit=100,
        factual_support=20,
        spoiler_risk=0,
    )

    assert evaluation.factual_support < FACTUAL_SUPPORT_FLOOR
    assert evaluation.overall_score == 20.0


def test_confidence_score_is_overall_score_normalized() -> None:
    evaluation = _evaluation()

    assert evaluation.confidence_score == pytest.approx(
        evaluation.overall_score / 100.0
    )


def test_score_dimensions_reject_out_of_range_values() -> None:
    with pytest.raises(ValidationError):
        _evaluation(immediate_curiosity=101)

    with pytest.raises(ValidationError):
        _evaluation(spoiler_risk=-1)
