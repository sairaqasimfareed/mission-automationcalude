from __future__ import annotations

from pathlib import Path

from src.models.final_export import FinalExportPackage
from src.models.final_export_validation import (
    FinalExportValidationCode,
    FinalExportValidationIssue,
    FinalExportValidationResult,
    FinalExportValidationSeverity,
)
from src.services.media_technical_validation_service import (
    MediaTechnicalValidationService,
)

# The per-clip defaults (Phase 8) assume a short individual clip - a
# finished video is routinely much longer, so the duration/resolution
# floor and ceiling are opened wide here. Real readability, video/audio
# stream presence, and (via the package's own declared resolution) a
# resolution-mismatch check are what this reuse is actually for.
_FINAL_VIDEO_MIN_DURATION_SECONDS = 0.1
_FINAL_VIDEO_MAX_DURATION_SECONDS = 86400.0
_FINAL_VIDEO_MIN_DIMENSION = 1


class FinalExportValidationService:
    """Independently validate a completed FinalExportPackage."""

    def __init__(
        self,
        *,
        technical_validation_service: MediaTechnicalValidationService | None = None,
    ) -> None:
        self._technical_validation_service = technical_validation_service or (
            MediaTechnicalValidationService(
                min_duration_seconds=(_FINAL_VIDEO_MIN_DURATION_SECONDS),
                max_duration_seconds=(_FINAL_VIDEO_MAX_DURATION_SECONDS),
                min_width=_FINAL_VIDEO_MIN_DIMENSION,
                min_height=_FINAL_VIDEO_MIN_DIMENSION,
            )
        )

    def validate(
        self,
        package: FinalExportPackage,
    ) -> FinalExportValidationResult:
        """Validate one FinalExportPackage and return a typed report."""

        errors: list[FinalExportValidationIssue] = []
        warnings: list[FinalExportValidationIssue] = []

        self._validate_video_file(package, errors=errors)
        self._validate_duration(package, errors=errors)
        self._validate_media_technical(package, errors=errors)
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

    def _validate_media_technical(
        self,
        package: FinalExportPackage,
        *,
        errors: list[FinalExportValidationIssue],
    ) -> None:
        """
        Run real, ffprobe-based technical validation on the final
        video file, reusing MediaTechnicalValidationService (Phase 8's
        clip acquisition QC gate) for the exact same readability check
        this phase's own "readable file, ... audio present" bullet
        asks for.

        Skipped for a URI-scheme placeholder path (dry-run mode) or a
        file that does not exist - the latter is already reported by
        _validate_video_file, and re-probing a file already known to
        be missing would only produce a redundant error.
        """

        if "://" in package.final_video_path:
            return

        video_path = Path(package.final_video_path)

        if not video_path.exists():
            return

        result = self._technical_validation_service.validate(video_path)

        if not result.is_readable or result.issues:
            detail = (
                "; ".join(result.issues) if result.issues else "file could not be read"
            )

            errors.append(
                FinalExportValidationIssue(
                    code=FinalExportValidationCode.MEDIA_NOT_READABLE,
                    severity=FinalExportValidationSeverity.ERROR,
                    message=("Final video failed technical validation: " f"{detail}."),
                    field="final_video_path",
                    metadata={"technical_issues": result.issues},
                )
            )

            return

        if not result.has_audio_stream:
            errors.append(
                FinalExportValidationIssue(
                    code=FinalExportValidationCode.MEDIA_NO_AUDIO_STREAM,
                    severity=FinalExportValidationSeverity.ERROR,
                    message="Final video file has no audio stream.",
                    field="final_video_path",
                )
            )

        expected_dimensions = self._parse_resolution(package.resolution)

        if (
            expected_dimensions is not None
            and result.width is not None
            and result.height is not None
            and (result.width, result.height) != expected_dimensions
        ):
            errors.append(
                FinalExportValidationIssue(
                    code=(FinalExportValidationCode.MEDIA_RESOLUTION_MISMATCH),
                    severity=FinalExportValidationSeverity.ERROR,
                    message=(
                        f"Final video is {result.width}x{result.height} "
                        f"but the package declares {package.resolution}."
                    ),
                    field="resolution",
                )
            )

    @staticmethod
    def _parse_resolution(
        resolution: str,
    ) -> tuple[int, int] | None:
        """
        Parse a "WIDTHxHEIGHT" resolution string.

        Returns None for an unparseable value rather than raising -
        an unrecognized format should skip the mismatch check, not
        crash final export validation.
        """

        parts = resolution.lower().split("x")

        if len(parts) != 2:
            return None

        try:
            return int(parts[0]), int(parts[1])
        except ValueError:
            return None

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
