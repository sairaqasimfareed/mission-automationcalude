from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.retention_audit import (
    RetentionAuditReport,
    RetentionFinding,
    RetentionIssueType,
)


def test_finding_rejects_empty_description() -> None:
    with pytest.raises(ValidationError):
        RetentionFinding(
            issue_type=RetentionIssueType.LOW_TENSION_VARIATION,
            description="   ",
        )


def test_report_rejects_genre_id_without_prefix() -> None:
    with pytest.raises(ValidationError):
        RetentionAuditReport(
            topic="The Mary Celeste",
            genre_id="mystery",
            reveal_count=2,
            expected_minimum_reveal_count=3,
        )


def test_report_with_no_findings_passes() -> None:
    report = RetentionAuditReport(
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        reveal_count=3,
        expected_minimum_reveal_count=3,
    )

    assert report.passed is True


def test_report_with_findings_does_not_pass() -> None:
    report = RetentionAuditReport(
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        reveal_count=1,
        expected_minimum_reveal_count=3,
        findings=[
            RetentionFinding(
                issue_type=RetentionIssueType.INSUFFICIENT_REVEAL_DENSITY,
                description="Only one reveal-type beat found.",
            )
        ],
    )

    assert report.passed is False
