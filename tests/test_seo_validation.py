from __future__ import annotations

from src.models.seo_validation import (
    SEOValidationCode,
    SEOValidationIssue,
    SEOValidationResult,
    SEOValidationSeverity,
)


def test_validation_result_defaults_to_no_issues() -> None:
    result = SEOValidationResult(is_valid=True)

    assert result.errors == []
    assert result.warnings == []
    assert result.issue_count == 0
    assert result.has_warnings is False


def test_validation_result_counts_errors_and_warnings_separately() -> None:
    result = SEOValidationResult(
        is_valid=False,
        errors=[
            SEOValidationIssue(
                code=SEOValidationCode.NO_SELECTED_TITLE,
                severity=SEOValidationSeverity.ERROR,
                message="No title was selected.",
            ),
        ],
        warnings=[
            SEOValidationIssue(
                code=SEOValidationCode.DUPLICATE_TAG,
                severity=SEOValidationSeverity.WARNING,
                message="Duplicate tag removed.",
            ),
            SEOValidationIssue(
                code=SEOValidationCode.DUPLICATE_HASHTAG,
                severity=SEOValidationSeverity.WARNING,
                message="Duplicate hashtag removed.",
            ),
        ],
    )

    assert result.issue_count == 3
    assert result.has_warnings is True
    assert len(result.errors) == 1
    assert len(result.warnings) == 2


def test_validation_issue_carries_optional_field_and_metadata() -> None:
    issue = SEOValidationIssue(
        code=SEOValidationCode.TITLE_TOO_LONG,
        severity=SEOValidationSeverity.ERROR,
        message="Title exceeds the platform limit.",
        field="selected_title",
        metadata={"max_length": "100"},
    )

    assert issue.field == "selected_title"
    assert issue.metadata == {"max_length": "100"}
