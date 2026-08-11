from __future__ import annotations

from uuid import uuid4

from src.models.enums import Platform
from src.models.seo import (
    SEOKeywordSet,
    SEOPackage,
    SEOPlatformMetadata,
    TitleCandidate,
)
from src.models.seo_validation import SEOValidationCode
from src.services.seo.seo_platform_metadata_service import (
    SEOPlatformMetadataService,
)
from src.services.seo.seo_validation_service import SEOValidationService

_YOUTUBE_CONSTRAINTS = SEOPlatformMetadataService().constraints_for(
    Platform.YOUTUBE,
)


def _platform_metadata(language: str = "English") -> SEOPlatformMetadata:
    return SEOPlatformMetadata(platform=Platform.YOUTUBE, language=language)


def _valid_package() -> SEOPackage:
    return SEOPackage(
        video_job_id=uuid4(),
        title_candidates=[TitleCandidate(text="Deep Sea Creatures Explained")],
        selected_title="Deep Sea Creatures Explained",
        description="A complete, publish-ready description.",
        keywords=SEOKeywordSet(primary_keywords=["ocean"]),
        tags=["ocean"],
        hashtags=["#ocean"],
        platform_metadata=_platform_metadata(),
        prompt_version="seo_prompt_v1.0.0",
    )


def test_validate_accepts_a_fully_valid_package() -> None:
    result = SEOValidationService().validate(
        _valid_package(),
        constraints=_YOUTUBE_CONSTRAINTS,
    )

    assert result.is_valid is True
    assert result.errors == []


def test_validate_flags_missing_selected_title() -> None:
    package = _valid_package().model_copy(
        update={"selected_title": None},
    )

    result = SEOValidationService().validate(
        package,
        constraints=_YOUTUBE_CONSTRAINTS,
    )

    codes = [issue.code for issue in result.errors]

    assert result.is_valid is False
    assert SEOValidationCode.NO_SELECTED_TITLE in codes


def test_validate_flags_no_title_candidates() -> None:
    package = _valid_package().model_copy(
        update={
            "title_candidates": [],
            "selected_title": None,
        },
    )

    result = SEOValidationService().validate(
        package,
        constraints=_YOUTUBE_CONSTRAINTS,
    )

    codes = [issue.code for issue in result.errors]

    assert SEOValidationCode.NO_TITLE_CANDIDATES in codes


def test_validate_flags_title_exceeding_platform_limit() -> None:
    long_title = "A" * 150

    package = _valid_package().model_copy(
        update={
            "title_candidates": [TitleCandidate(text=long_title)],
            "selected_title": long_title,
        },
    )

    result = SEOValidationService().validate(
        package,
        constraints=_YOUTUBE_CONSTRAINTS,
    )

    codes = [issue.code for issue in result.errors]

    assert result.is_valid is False
    assert SEOValidationCode.TITLE_TOO_LONG in codes


def test_validate_warns_on_duplicate_title_candidates() -> None:
    package = _valid_package().model_copy(
        update={
            "title_candidates": [
                TitleCandidate(text="Deep Sea Creatures Explained"),
                TitleCandidate(text="deep sea creatures explained"),
            ],
        },
    )

    result = SEOValidationService().validate(
        package,
        constraints=_YOUTUBE_CONSTRAINTS,
    )

    codes = [issue.code for issue in result.warnings]

    assert result.is_valid is True
    assert SEOValidationCode.DUPLICATE_TITLE_CANDIDATE in codes


def test_validate_flags_empty_description() -> None:
    package = _valid_package().model_copy(update={"description": "   "})

    result = SEOValidationService().validate(
        package,
        constraints=_YOUTUBE_CONSTRAINTS,
    )

    codes = [issue.code for issue in result.errors]

    assert result.is_valid is False
    assert SEOValidationCode.EMPTY_DESCRIPTION in codes


def test_validate_flags_description_exceeding_platform_limit() -> None:
    package = _valid_package().model_copy(
        update={"description": "A" * 6000},
    )

    result = SEOValidationService().validate(
        package,
        constraints=_YOUTUBE_CONSTRAINTS,
    )

    codes = [issue.code for issue in result.errors]

    assert SEOValidationCode.DESCRIPTION_TOO_LONG in codes


def test_validate_warns_on_no_keywords() -> None:
    package = _valid_package().model_copy(
        update={"keywords": SEOKeywordSet()},
    )

    result = SEOValidationService().validate(
        package,
        constraints=_YOUTUBE_CONSTRAINTS,
    )

    codes = [issue.code for issue in result.warnings]

    assert result.is_valid is True
    assert SEOValidationCode.NO_KEYWORDS in codes


def test_validate_warns_on_keyword_duplicated_across_categories() -> None:
    package = _valid_package().model_copy(
        update={
            "keywords": SEOKeywordSet(
                primary_keywords=["ocean"],
                secondary_keywords=["ocean"],
            ),
        },
    )

    result = SEOValidationService().validate(
        package,
        constraints=_YOUTUBE_CONSTRAINTS,
    )

    codes = [issue.code for issue in result.warnings]

    assert SEOValidationCode.DUPLICATE_KEYWORD in codes


def test_validate_flags_too_many_tags() -> None:
    package = _valid_package().model_copy(
        update={"tags": [f"tag{index}" for index in range(40)]},
    )

    result = SEOValidationService().validate(
        package,
        constraints=_YOUTUBE_CONSTRAINTS,
    )

    codes = [issue.code for issue in result.errors]

    assert result.is_valid is False
    assert SEOValidationCode.TOO_MANY_TAGS in codes


def test_validate_flags_too_many_hashtags() -> None:
    package = _valid_package().model_copy(
        update={"hashtags": [f"#tag{index}" for index in range(20)]},
    )

    result = SEOValidationService().validate(
        package,
        constraints=_YOUTUBE_CONSTRAINTS,
    )

    codes = [issue.code for issue in result.errors]

    assert result.is_valid is False
    assert SEOValidationCode.TOO_MANY_HASHTAGS in codes


def test_validate_warns_on_language_mismatch() -> None:
    result = SEOValidationService().validate(
        _valid_package(),
        constraints=_YOUTUBE_CONSTRAINTS,
        expected_language="French",
    )

    codes = [issue.code for issue in result.warnings]

    assert result.is_valid is True
    assert SEOValidationCode.LANGUAGE_MISMATCH in codes


def test_validate_skips_language_check_when_not_expected() -> None:
    result = SEOValidationService().validate(
        _valid_package(),
        constraints=_YOUTUBE_CONSTRAINTS,
    )

    codes = [issue.code for issue in result.warnings]

    assert SEOValidationCode.LANGUAGE_MISMATCH not in codes
