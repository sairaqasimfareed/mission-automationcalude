from __future__ import annotations

from src.models.final_export_validation import (
    FinalExportValidationCode,
    FinalExportValidationIssue,
    FinalExportValidationResult,
    FinalExportValidationSeverity,
)


def test_validation_result_defaults_to_no_issues() -> None:
    result = FinalExportValidationResult(is_valid=True)

    assert result.errors == []
    assert result.warnings == []
    assert result.issue_count == 0
    assert result.has_warnings is False


def test_validation_result_counts_errors_and_warnings_separately() -> None:
    result = FinalExportValidationResult(
        is_valid=False,
        errors=[
            FinalExportValidationIssue(
                code=FinalExportValidationCode.VIDEO_FILE_MISSING,
                severity=FinalExportValidationSeverity.ERROR,
                message="Final video file does not exist.",
            ),
        ],
        warnings=[
            FinalExportValidationIssue(
                code=FinalExportValidationCode.MANIFEST_MISSING,
                severity=FinalExportValidationSeverity.WARNING,
                message="Export manifest was not written.",
            ),
        ],
    )

    assert result.issue_count == 2
    assert result.has_warnings is True
    assert len(result.errors) == 1
    assert len(result.warnings) == 1


def test_validation_issue_carries_optional_field_and_metadata() -> None:
    issue = FinalExportValidationIssue(
        code=FinalExportValidationCode.INVALID_DURATION,
        severity=FinalExportValidationSeverity.ERROR,
        message="Duration is invalid.",
        field="duration_seconds",
        metadata={"duration_seconds": "0"},
    )

    assert issue.field == "duration_seconds"
    assert issue.metadata == {"duration_seconds": "0"}
