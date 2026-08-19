from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.editorial_critique import (
    CHARACTER_DEPENDENT_DIMENSIONS,
    CriticFinding,
    EditorialCritique,
    FindingSeverity,
    QualityDimension,
)


def _finding(**overrides: object) -> CriticFinding:
    base: dict[str, object] = dict(
        dimension=QualityDimension.RETENTION_ARCHITECTURE,
        severity=FindingSeverity.MAJOR,
        segment_number=2,
        problem="Segment 2 repeats the hook's claim verbatim.",
        reason="Repetition this early kills momentum for suspenseful genres.",
        recommended_correction="Cut the repeated sentence entirely.",
    )
    base.update(overrides)
    return CriticFinding(**base)


def test_finding_rejects_empty_problem_text() -> None:
    with pytest.raises(ValidationError):
        _finding(problem="   ")


def test_finding_segment_number_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        _finding(segment_number=0)


def test_finding_segment_number_may_be_none_for_whole_script_findings() -> None:
    finding = _finding(segment_number=None)

    assert finding.segment_number is None


def _critique(**overrides: object) -> EditorialCritique:
    base: dict[str, object] = dict(
        topic="The Mary Celeste",
        dimension_scores={"factual_confidence": 80, "hook_strength": 60},
        findings=[_finding()],
        prompt_version="editorial_critique_prompt_v1.0.0",
    )
    base.update(overrides)
    return EditorialCritique(**base)


def test_critique_rejects_unknown_dimension_key() -> None:
    with pytest.raises(ValidationError):
        _critique(dimension_scores={"not_a_real_dimension": 50})


def test_critique_rejects_out_of_range_score() -> None:
    with pytest.raises(ValidationError):
        _critique(dimension_scores={"hook_strength": 150})


def test_blocking_findings_filters_by_severity() -> None:
    blocking = _finding(severity=FindingSeverity.BLOCKING)
    minor = _finding(severity=FindingSeverity.MINOR)

    critique = _critique(findings=[blocking, minor])

    assert critique.blocking_findings == [blocking]


def test_major_findings_filters_by_severity() -> None:
    major = _finding(severity=FindingSeverity.MAJOR)
    minor = _finding(severity=FindingSeverity.MINOR)

    critique = _critique(findings=[major, minor])

    assert critique.major_findings == [major]


def test_character_dependent_dimensions_are_exactly_character_and_payoff() -> None:
    assert CHARACTER_DEPENDENT_DIMENSIONS == {
        QualityDimension.CHARACTER_DEPTH,
        QualityDimension.PAYOFF_STRENGTH,
    }
