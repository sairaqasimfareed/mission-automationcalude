from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.editorial_critique import (
    CriticFinding,
    FindingSeverity,
    QualityDimension,
)
from src.models.script_quality_report import (
    FindingResolution,
    FindingResolutionAction,
    ScriptQualityReport,
    ScriptQualityStatus,
)


def _finding(
    *,
    dimension: QualityDimension = QualityDimension.RETENTION_ARCHITECTURE,
    severity: FindingSeverity = FindingSeverity.BLOCKING,
    segment_number: int | None = 1,
    problem: str = "Unsupported claim.",
    reason: str = "No source backs this.",
    recommended_correction: str = "Remove or attribute the claim.",
) -> CriticFinding:
    return CriticFinding(
        dimension=dimension,
        severity=severity,
        segment_number=segment_number,
        problem=problem,
        reason=reason,
        recommended_correction=recommended_correction,
    )


def _report(
    *,
    topic: str = "The Mary Celeste",
    genre_id: str = "genre.mystery",
    dimension_scores: dict[str, int] | None = None,
    dimension_thresholds: dict[str, int] | None = None,
    failed_dimensions: list[str] | None = None,
    blocking_findings: list[CriticFinding] | None = None,
    major_findings: list[CriticFinding] | None = None,
    status: ScriptQualityStatus = ScriptQualityStatus.APPROVED_FOR_PRODUCTION,
    resolutions: list[FindingResolution] | None = None,
) -> ScriptQualityReport:
    return ScriptQualityReport(
        topic=topic,
        genre_id=genre_id,
        dimension_scores=(
            dimension_scores if dimension_scores is not None else {"hook_strength": 70}
        ),
        dimension_thresholds=(
            dimension_thresholds
            if dimension_thresholds is not None
            else {"hook_strength": 55}
        ),
        failed_dimensions=failed_dimensions if failed_dimensions is not None else [],
        blocking_findings=blocking_findings if blocking_findings is not None else [],
        major_findings=major_findings if major_findings is not None else [],
        status=status,
        resolutions=resolutions if resolutions is not None else [],
    )


def test_report_rejects_genre_id_without_prefix() -> None:
    with pytest.raises(ValidationError):
        _report(genre_id="mystery")


def test_passed_true_only_for_approved_status() -> None:
    assert _report(status=ScriptQualityStatus.APPROVED_FOR_PRODUCTION).passed is True
    assert _report(status=ScriptQualityStatus.NEEDS_REVISION).passed is False
    assert _report(status=ScriptQualityStatus.EDITORIAL_REVIEW).passed is False
    assert _report(status=ScriptQualityStatus.DRAFT).passed is False


def test_defaults_have_no_version_binding_or_resolutions() -> None:
    report = _report()

    assert report.script_version_number is None
    assert report.script_content_hash is None
    assert report.resolutions == []


def test_ignored_resolution_requires_a_reason() -> None:
    with pytest.raises(ValidationError, match="requires a non-empty reason"):
        FindingResolution(
            finding_id=_finding().id, action=FindingResolutionAction.IGNORED
        )


def test_applied_resolution_does_not_require_a_reason() -> None:
    resolution = FindingResolution(
        finding_id=_finding().id, action=FindingResolutionAction.APPLIED
    )

    assert resolution.reason is None


def test_all_findings_combines_blocking_and_major() -> None:
    blocking = _finding(severity=FindingSeverity.BLOCKING)
    major = _finding(severity=FindingSeverity.MAJOR)
    report = _report(blocking_findings=[blocking], major_findings=[major])

    assert report.all_findings == [blocking, major]


def test_resolution_for_returns_the_matching_resolution() -> None:
    finding = _finding()
    resolution = FindingResolution(
        finding_id=finding.id,
        action=FindingResolutionAction.IGNORED,
        reason="Acceptable creative license for this genre.",
    )
    report = _report(blocking_findings=[finding], resolutions=[resolution])

    assert report.resolution_for(finding.id) == resolution


def test_resolution_for_returns_none_when_unresolved() -> None:
    finding = _finding()
    report = _report(blocking_findings=[finding])

    assert report.resolution_for(finding.id) is None


def test_unresolved_blocking_findings_excludes_resolved_ones() -> None:
    resolved = _finding()
    unresolved = _finding(problem="A second unsupported claim.")
    resolution = FindingResolution(
        finding_id=resolved.id,
        action=FindingResolutionAction.IGNORED,
        reason="Confirmed acceptable.",
    )
    report = _report(blocking_findings=[resolved, unresolved], resolutions=[resolution])

    assert report.unresolved_blocking_findings == [unresolved]
