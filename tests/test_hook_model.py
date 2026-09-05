from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.genre_profile import HookArchetype
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


def test_phase_10_candidate_fields_default_to_empty() -> None:
    candidate = HookCandidate(text="The crew vanished without a trace.")

    assert candidate.type is None
    assert candidate.fact_ids == []


def test_candidate_can_carry_type_and_fact_ids() -> None:
    from uuid import uuid4

    fact_id = uuid4()
    candidate = HookCandidate(
        text="The crew vanished without a trace.",
        type=HookArchetype.MYSTERY,
        fact_ids=[fact_id],
    )

    assert candidate.type == HookArchetype.MYSTERY
    assert candidate.fact_ids == [fact_id]


def test_phase_10_evaluation_fields_default_to_none_and_false() -> None:
    evaluation = _evaluation()

    assert evaluation.retention_potential is None
    assert evaluation.tone_fit is None
    assert evaluation.is_custom is False


def test_optional_dimensions_are_not_folded_into_overall_score() -> None:
    without_optionals = _evaluation()
    with_optionals = _evaluation(retention_potential=100, tone_fit=100)

    assert without_optionals.overall_score == with_optionals.overall_score


def test_custom_hook_evaluation_is_flagged_and_unscored() -> None:
    evaluation = HookEvaluation.custom("A hook I wrote myself.")

    assert evaluation.is_custom is True
    assert evaluation.hook_text == "A hook I wrote myself."
    assert evaluation.overall_score == 0.0
    assert evaluation.retention_potential is None


def test_backward_compatible_round_trip_without_phase_10_fields() -> None:
    candidate = HookCandidate(text="The crew vanished without a trace.")
    evaluation = _evaluation()

    reloaded_candidate = HookCandidate.model_validate_json(candidate.model_dump_json())
    reloaded_evaluation = HookEvaluation.model_validate_json(
        evaluation.model_dump_json()
    )

    assert reloaded_candidate.type is None
    assert reloaded_candidate.fact_ids == []
    assert reloaded_evaluation.retention_potential is None
    assert reloaded_evaluation.is_custom is False
