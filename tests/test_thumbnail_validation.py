from __future__ import annotations

from src.models.thumbnail_validation import (
    ThumbnailValidationCode,
    ThumbnailValidationIssue,
    ThumbnailValidationResult,
    ThumbnailValidationSeverity,
)


def test_validation_result_defaults_to_no_issues() -> None:
    result = ThumbnailValidationResult(is_valid=True)

    assert result.errors == []
    assert result.warnings == []
    assert result.issue_count == 0
    assert result.has_warnings is False


def test_validation_result_counts_errors_and_warnings_separately() -> None:
    result = ThumbnailValidationResult(
        is_valid=False,
        errors=[
            ThumbnailValidationIssue(
                code=ThumbnailValidationCode.FILE_MISSING,
                severity=ThumbnailValidationSeverity.ERROR,
                message="Thumbnail file does not exist.",
            ),
        ],
        warnings=[
            ThumbnailValidationIssue(
                code=ThumbnailValidationCode.HOOK_TEXT_TOO_LONG,
                severity=ThumbnailValidationSeverity.WARNING,
                message="Hook text is long.",
            ),
        ],
    )

    assert result.issue_count == 2
    assert result.has_warnings is True
    assert len(result.errors) == 1
    assert len(result.warnings) == 1


def test_validation_issue_carries_optional_field_and_metadata() -> None:
    issue = ThumbnailValidationIssue(
        code=ThumbnailValidationCode.INVALID_DIMENSIONS,
        severity=ThumbnailValidationSeverity.ERROR,
        message="Thumbnail dimensions are invalid.",
        field="layout",
        metadata={"width": "0"},
    )

    assert issue.field == "layout"
    assert issue.metadata == {"width": "0"}
