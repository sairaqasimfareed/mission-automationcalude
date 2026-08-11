from __future__ import annotations

from pathlib import Path

from src.models.final_export import FinalExportPackage
from src.models.final_export_validation import (
    FinalExportValidationCode,
    FinalExportValidationIssue,
    FinalExportValidationResult,
    FinalExportValidationSeverity,
)


class FinalExportValidationService:
    """Independently validate a completed FinalExportPackage."""

    def validate(
        self,
        package: FinalExportPackage,
    ) -> FinalExportValidationResult:
        """Validate one FinalExportPackage and return a typed report."""

        errors: list[FinalExportValidationIssue] = []
        warnings: list[FinalExportValidationIssue] = []

        self._validate_video_file(package, errors=errors)
        self._validate_duration(package, errors=errors)
        self._validate_manifest(package, errors=errors)
        self._validate_thumbnail_readiness(package, warnings=warnings)
        self._validate_seo_readiness(package, warnings=warnings)

        return FinalExportValidationResult(
            is_valid=not errors,
            errors=errors,
            warnings=warnings,
        )

    @staticmethod
    def _validate_video_file(
        package: FinalExportPackage,
        *,
        errors: list[FinalExportValidationIssue],
    ) -> None:
        if "://" in package.final_video_path:
            return

        if not Path(package.final_video_path).exists():
            errors.append(
                FinalExportValidationIssue(
                    code=FinalExportValidationCode.VIDEO_FILE_MISSING,
                    severity=FinalExportValidationSeverity.ERROR,
                    message=(
                        "Final video file does not exist: "
                        f"{package.final_video_path}"
                    ),
                    field="final_video_path",
                )
            )

    @staticmethod
    def _validate_duration(
        package: FinalExportPackage,
        *,
        errors: list[FinalExportValidationIssue],
    ) -> None:
        if package.duration_seconds <= 0:
            errors.append(
                FinalExportValidationIssue(
                    code=FinalExportValidationCode.INVALID_DURATION,
                    severity=FinalExportValidationSeverity.ERROR,
                    message="Final export duration must be greater than zero.",
                    field="duration_seconds",
                    metadata={"duration_seconds": str(package.duration_seconds)},
                )
            )

    @staticmethod
    def _validate_manifest(
        package: FinalExportPackage,
        *,
        errors: list[FinalExportValidationIssue],
    ) -> None:
        if package.manifest_path is None or not Path(package.manifest_path).exists():
            errors.append(
                FinalExportValidationIssue(
                    code=FinalExportValidationCode.MANIFEST_MISSING,
                    severity=FinalExportValidationSeverity.ERROR,
                    message="Export manifest was not written.",
                    field="manifest_path",
                )
            )

    @staticmethod
    def _validate_thumbnail_readiness(
        package: FinalExportPackage,
        *,
        warnings: list[FinalExportValidationIssue],
    ) -> None:
        if not package.thumbnail_artifact.is_ready_for_export:
            warnings.append(
                FinalExportValidationIssue(
                    code=FinalExportValidationCode.THUMBNAIL_NOT_READY,
                    severity=FinalExportValidationSeverity.WARNING,
                    message="Thumbnail artifact has not been approved.",
                    field="thumbnail_artifact.status",
                )
            )

    @staticmethod
    def _validate_seo_readiness(
        package: FinalExportPackage,
        *,
        warnings: list[FinalExportValidationIssue],
    ) -> None:
        if not package.seo_package.is_ready_for_export:
            warnings.append(
                FinalExportValidationIssue(
                    code=FinalExportValidationCode.SEO_PACKAGE_NOT_READY,
                    severity=FinalExportValidationSeverity.WARNING,
                    message="SEO package has not been approved.",
                    field="seo_package.status",
                )
            )
