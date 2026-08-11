from __future__ import annotations

from src.models.seo import SEOPackage
from src.models.seo_validation import (
    SEOValidationCode,
    SEOValidationIssue,
    SEOValidationResult,
    SEOValidationSeverity,
)
from src.services.seo.seo_platform_metadata_service import (
    PlatformConstraints,
)


class SEOValidationService:
    """
    Independently validate a completed SEOPackage against structural
    and platform-specific constraints.

    Several conditions this service could otherwise check (a selected
    title outside the candidate set, duplicate tags/hashtags, a
    missing platform_metadata) are already impossible to construct:
    SEOPackage's own field validators enforce them at the model level.
    This service focuses on conditions the model cannot enforce by
    itself - length limits, cross-field consistency, and
    platform-specific bounds.
    """

    def validate(
        self,
        package: SEOPackage,
        *,
        constraints: PlatformConstraints,
        expected_language: str | None = None,
    ) -> SEOValidationResult:
        """Validate one SEOPackage and return a typed report."""

        errors: list[SEOValidationIssue] = []
        warnings: list[SEOValidationIssue] = []

        self._validate_titles(package, errors=errors, warnings=warnings)

        self._validate_title_length(
            package,
            constraints=constraints,
            errors=errors,
        )

        self._validate_description(
            package,
            constraints=constraints,
            errors=errors,
        )

        self._validate_keywords(package, warnings=warnings)

        self._validate_bounded_counts(
            package,
            constraints=constraints,
            errors=errors,
        )

        self._validate_language(
            package,
            expected_language=expected_language,
            warnings=warnings,
        )

        return SEOValidationResult(
            is_valid=not errors,
            errors=errors,
            warnings=warnings,
        )

    @staticmethod
    def _validate_titles(
        package: SEOPackage,
        *,
        errors: list[SEOValidationIssue],
        warnings: list[SEOValidationIssue],
    ) -> None:
        if not package.title_candidates:
            errors.append(
                SEOValidationIssue(
                    code=SEOValidationCode.NO_TITLE_CANDIDATES,
                    severity=SEOValidationSeverity.ERROR,
                    message="SEO package has no title candidates.",
                    field="title_candidates",
                )
            )

        if package.selected_title is None:
            errors.append(
                SEOValidationIssue(
                    code=SEOValidationCode.NO_SELECTED_TITLE,
                    severity=SEOValidationSeverity.ERROR,
                    message="SEO package has no selected title.",
                    field="selected_title",
                )
            )

        seen_texts: set[str] = set()

        for candidate in package.title_candidates:
            normalized = candidate.text.strip().lower()

            if normalized in seen_texts:
                warnings.append(
                    SEOValidationIssue(
                        code=SEOValidationCode.DUPLICATE_TITLE_CANDIDATE,
                        severity=SEOValidationSeverity.WARNING,
                        message=("Duplicate title candidate: " f"'{candidate.text}'."),
                        field="title_candidates",
                    )
                )
                continue

            seen_texts.add(normalized)

    @staticmethod
    def _validate_title_length(
        package: SEOPackage,
        *,
        constraints: PlatformConstraints,
        errors: list[SEOValidationIssue],
    ) -> None:
        if package.selected_title is None:
            return

        if len(package.selected_title) > constraints.max_title_length:
            errors.append(
                SEOValidationIssue(
                    code=SEOValidationCode.TITLE_TOO_LONG,
                    severity=SEOValidationSeverity.ERROR,
                    message=(
                        "Selected title exceeds the platform limit of "
                        f"{constraints.max_title_length} characters."
                    ),
                    field="selected_title",
                    metadata={
                        "max_length": str(constraints.max_title_length),
                        "actual_length": str(len(package.selected_title)),
                    },
                )
            )

    @staticmethod
    def _validate_description(
        package: SEOPackage,
        *,
        constraints: PlatformConstraints,
        errors: list[SEOValidationIssue],
    ) -> None:
        if not package.description.strip():
            errors.append(
                SEOValidationIssue(
                    code=SEOValidationCode.EMPTY_DESCRIPTION,
                    severity=SEOValidationSeverity.ERROR,
                    message="SEO package description is empty.",
                    field="description",
                )
            )
            return

        if len(package.description) > constraints.max_description_length:
            errors.append(
                SEOValidationIssue(
                    code=SEOValidationCode.DESCRIPTION_TOO_LONG,
                    severity=SEOValidationSeverity.ERROR,
                    message=(
                        "Description exceeds the platform limit of "
                        f"{constraints.max_description_length} characters."
                    ),
                    field="description",
                    metadata={
                        "max_length": str(constraints.max_description_length),
                        "actual_length": str(len(package.description)),
                    },
                )
            )

    @staticmethod
    def _validate_keywords(
        package: SEOPackage,
        *,
        warnings: list[SEOValidationIssue],
    ) -> None:
        keywords = package.keywords

        all_keywords = (
            keywords.primary_keywords
            + keywords.secondary_keywords
            + keywords.long_tail_keywords
        )

        if not all_keywords:
            warnings.append(
                SEOValidationIssue(
                    code=SEOValidationCode.NO_KEYWORDS,
                    severity=SEOValidationSeverity.WARNING,
                    message="SEO package has no keywords in any category.",
                    field="keywords",
                )
            )
            return

        seen: set[str] = set()

        for keyword in all_keywords:
            if keyword in seen:
                warnings.append(
                    SEOValidationIssue(
                        code=SEOValidationCode.DUPLICATE_KEYWORD,
                        severity=SEOValidationSeverity.WARNING,
                        message=(
                            f"Keyword '{keyword}' appears in more than "
                            "one keyword category."
                        ),
                        field="keywords",
                    )
                )
                continue

            seen.add(keyword)

    @staticmethod
    def _validate_bounded_counts(
        package: SEOPackage,
        *,
        constraints: PlatformConstraints,
        errors: list[SEOValidationIssue],
    ) -> None:
        if len(package.tags) > constraints.max_tags:
            errors.append(
                SEOValidationIssue(
                    code=SEOValidationCode.TOO_MANY_TAGS,
                    severity=SEOValidationSeverity.ERROR,
                    message=(
                        "Tag count exceeds the platform limit of "
                        f"{constraints.max_tags}."
                    ),
                    field="tags",
                    metadata={
                        "max_count": str(constraints.max_tags),
                        "actual_count": str(len(package.tags)),
                    },
                )
            )

        if len(package.hashtags) > constraints.max_hashtags:
            errors.append(
                SEOValidationIssue(
                    code=SEOValidationCode.TOO_MANY_HASHTAGS,
                    severity=SEOValidationSeverity.ERROR,
                    message=(
                        "Hashtag count exceeds the platform limit of "
                        f"{constraints.max_hashtags}."
                    ),
                    field="hashtags",
                    metadata={
                        "max_count": str(constraints.max_hashtags),
                        "actual_count": str(len(package.hashtags)),
                    },
                )
            )

    @staticmethod
    def _validate_language(
        package: SEOPackage,
        *,
        expected_language: str | None,
        warnings: list[SEOValidationIssue],
    ) -> None:
        if expected_language is None:
            return

        if package.platform_metadata.language != expected_language:
            warnings.append(
                SEOValidationIssue(
                    code=SEOValidationCode.LANGUAGE_MISMATCH,
                    severity=SEOValidationSeverity.WARNING,
                    message=(
                        "Platform metadata language "
                        f"'{package.platform_metadata.language}' does not "
                        f"match expected language '{expected_language}'."
                    ),
                    field="platform_metadata.language",
                )
            )
