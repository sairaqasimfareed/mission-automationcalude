from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.script_quality_report import ScriptQualityReport, ScriptQualityStatus


def _report(**overrides: object) -> ScriptQualityReport:
    base: dict[str, object] = dict(
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        dimension_scores={"hook_strength": 70},
        dimension_thresholds={"hook_strength": 55},
        failed_dimensions=[],
        blocking_findings=[],
        major_findings=[],
        status=ScriptQualityStatus.APPROVED_FOR_PRODUCTION,
    )
    base.update(overrides)
    return ScriptQualityReport(**base)


def test_report_rejects_genre_id_without_prefix() -> None:
    with pytest.raises(ValidationError):
        _report(genre_id="mystery")


def test_passed_true_only_for_approved_status() -> None:
    assert _report(status=ScriptQualityStatus.APPROVED_FOR_PRODUCTION).passed is True
    assert _report(status=ScriptQualityStatus.NEEDS_REVISION).passed is False
    assert _report(status=ScriptQualityStatus.EDITORIAL_REVIEW).passed is False
    assert _report(status=ScriptQualityStatus.DRAFT).passed is False
