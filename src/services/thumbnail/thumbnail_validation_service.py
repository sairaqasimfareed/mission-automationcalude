from __future__ import annotations

from pathlib import Path

from src.models.thumbnail import ThumbnailArtifact
from src.models.thumbnail_validation import (
    ThumbnailValidationCode,
    ThumbnailValidationIssue,
    ThumbnailValidationResult,
    ThumbnailValidationSeverity,
)

_MAX_HOOK_TEXT_LENGTH = 60
_ASSUMED_GLYPH_WIDTH_RATIO = 0.6


class ThumbnailValidationService:
    """
    Independently validate a completed ThumbnailArtifact.

    No image-rendering or pixel-inspection library is available in
    this project, so "safe composition bounds" is checked with a
    deterministic text-length estimate rather than by measuring an
    actual rendered image. This is a documented approximation, not a
    pixel-accurate check.
    """

    def validate(
        self,
        artifact: ThumbnailArtifact,
        *,
        expected_dimensions: tuple[int, int] | None = None,
    ) -> ThumbnailValidationResult:
        """Validate one ThumbnailArtifact and return a typed report."""

        errors: list[ThumbnailValidationIssue] = []
        warnings: list[ThumbnailValidationIssue] = []

        self._validate_file_exists(artifact, errors=errors)

        self._validate_dimensions(
            artifact,
            expected_dimensions=expected_dimensions,
            errors=errors,
        )

        self._validate_hook_text_length(artifact, warnings=warnings)

        self._validate_hook_text_safe_margin(artifact, warnings=warnings)

        return ThumbnailValidationResult(
            is_valid=not errors,
            errors=errors,
            warnings=warnings,
        )

    @staticmethod
    def _validate_file_exists(
        artifact: ThumbnailArtifact,
        *,
        errors: list[ThumbnailValidationIssue],
    ) -> None:
        if "://" in artifact.file_path:
            # A URI-scheme placeholder path (for example a dry-run
            # provider's output) is not a real filesystem artifact and
            # is not expected to exist.
            return

        if not Path(artifact.file_path).exists():
            errors.append(
                ThumbnailValidationIssue(
                    code=ThumbnailValidationCode.FILE_MISSING,
                    severity=ThumbnailValidationSeverity.ERROR,
                    message=(f"Thumbnail file does not exist: {artifact.file_path}"),
                    field="file_path",
                )
            )

    @staticmethod
    def _validate_dimensions(
        artifact: ThumbnailArtifact,
        *,
        expected_dimensions: tuple[int, int] | None,
        errors: list[ThumbnailValidationIssue],
    ) -> None:
        if expected_dimensions is None:
            return

        actual = (artifact.layout.width, artifact.layout.height)

        if actual != expected_dimensions:
            errors.append(
                ThumbnailValidationIssue(
                    code=ThumbnailValidationCode.INVALID_DIMENSIONS,
                    severity=ThumbnailValidationSeverity.ERROR,
                    message=(
                        f"Thumbnail dimensions {actual} do not match the "
                        f"expected platform dimensions {expected_dimensions}."
                    ),
                    field="layout",
                    metadata={
                        "expected": str(expected_dimensions),
                        "actual": str(actual),
                    },
                )
            )

    @staticmethod
    def _validate_hook_text_length(
        artifact: ThumbnailArtifact,
        *,
        warnings: list[ThumbnailValidationIssue],
    ) -> None:
        hook_text = artifact.concept.hook_text

        if len(hook_text) > _MAX_HOOK_TEXT_LENGTH:
            warnings.append(
                ThumbnailValidationIssue(
                    code=ThumbnailValidationCode.HOOK_TEXT_TOO_LONG,
                    severity=ThumbnailValidationSeverity.WARNING,
                    message=(
                        "Hook text exceeds the recommended "
                        f"{_MAX_HOOK_TEXT_LENGTH} characters."
                    ),
                    field="concept.hook_text",
                    metadata={"length": str(len(hook_text))},
                )
            )

    @staticmethod
    def _validate_hook_text_safe_margin(
        artifact: ThumbnailArtifact,
        *,
        warnings: list[ThumbnailValidationIssue],
    ) -> None:
        layout = artifact.layout
        hook_text = artifact.concept.hook_text

        estimated_font_height = layout.hook_text_font_scale * layout.height

        estimated_text_width = (
            len(hook_text) * estimated_font_height * _ASSUMED_GLYPH_WIDTH_RATIO
        )

        safe_width = layout.width * (1 - 2 * layout.safe_margin_ratio)

        if estimated_text_width > safe_width:
            warnings.append(
                ThumbnailValidationIssue(
                    code=ThumbnailValidationCode.HOOK_TEXT_OUTSIDE_SAFE_MARGIN,
                    severity=ThumbnailValidationSeverity.WARNING,
                    message=(
                        "Hook text is estimated to exceed the layout's "
                        "safe composition margin at the configured font "
                        "scale."
                    ),
                    field="layout.hook_text_font_scale",
                    metadata={
                        "estimated_text_width": str(round(estimated_text_width, 2)),
                        "safe_width": str(round(safe_width, 2)),
                    },
                )
            )
