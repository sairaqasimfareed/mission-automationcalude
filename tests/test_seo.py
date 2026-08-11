from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.models.enums import Platform
from src.models.seo import (
    SEOKeywordSet,
    SEOPackage,
    SEOPlatformMetadata,
    SEOStatus,
    TitleCandidate,
)


def _platform_metadata() -> SEOPlatformMetadata:
    return SEOPlatformMetadata(platform=Platform.YOUTUBE)


def test_title_candidate_strips_text() -> None:
    candidate = TitleCandidate(text="  My Great Title  ")

    assert candidate.text == "My Great Title"


def test_title_candidate_rejects_empty_text() -> None:
    with pytest.raises(ValidationError):
        TitleCandidate(text="   ")


def test_title_candidate_overall_score_penalizes_clickbait_risk() -> None:
    honest_candidate = TitleCandidate(
        text="Honest Title",
        relevance_score=80,
        clarity_score=80,
        curiosity_score=80,
        specificity_score=80,
        audience_fit_score=80,
        clickbait_risk_score=0,
    )

    clickbait_candidate = TitleCandidate(
        text="You Won't Believe This",
        relevance_score=80,
        clarity_score=80,
        curiosity_score=80,
        specificity_score=80,
        audience_fit_score=80,
        clickbait_risk_score=100,
    )

    assert honest_candidate.overall_score > clickbait_candidate.overall_score
    assert honest_candidate.overall_score == 80.0


def test_keyword_set_deduplicates_and_normalizes() -> None:
    keywords = SEOKeywordSet(
        primary_keywords=["Python", "python", "  PYTHON  ", "Coding"],
    )

    assert keywords.primary_keywords == ["python", "coding"]


def test_keyword_set_keeps_categories_distinct() -> None:
    keywords = SEOKeywordSet(
        primary_keywords=["python"],
        secondary_keywords=["tutorial"],
        long_tail_keywords=["python tutorial for beginners"],
    )

    assert keywords.primary_keywords == ["python"]
    assert keywords.secondary_keywords == ["tutorial"]
    assert keywords.long_tail_keywords == ["python tutorial for beginners"]


def test_seo_package_requires_video_job_id() -> None:
    with pytest.raises(ValidationError):
        SEOPackage(  # type: ignore[call-arg]
            platform_metadata=_platform_metadata(),
            prompt_version="seo_prompt_v1.0.0",
        )


def test_seo_package_accepts_selected_title_matching_a_candidate() -> None:
    package = SEOPackage(
        video_job_id=uuid4(),
        title_candidates=[TitleCandidate(text="Great Video")],
        selected_title="Great Video",
        description="A great video about a great topic.",
        platform_metadata=_platform_metadata(),
        prompt_version="seo_prompt_v1.0.0",
    )

    assert package.selected_title == "Great Video"


def test_seo_package_rejects_selected_title_not_in_candidates() -> None:
    with pytest.raises(ValidationError, match="must match one of"):
        SEOPackage(
            video_job_id=uuid4(),
            title_candidates=[TitleCandidate(text="Great Video")],
            selected_title="A Different Title",
            platform_metadata=_platform_metadata(),
            prompt_version="seo_prompt_v1.0.0",
        )


def test_seo_package_allows_no_selected_title() -> None:
    package = SEOPackage(
        video_job_id=uuid4(),
        title_candidates=[TitleCandidate(text="Great Video")],
        platform_metadata=_platform_metadata(),
        prompt_version="seo_prompt_v1.0.0",
    )

    assert package.selected_title is None


def test_seo_package_normalizes_tags() -> None:
    package = SEOPackage(
        video_job_id=uuid4(),
        tags=["Python", "python", "  Coding  "],
        platform_metadata=_platform_metadata(),
        prompt_version="seo_prompt_v1.0.0",
    )

    assert package.tags == ["python", "coding"]


def test_seo_package_normalizes_hashtags() -> None:
    package = SEOPackage(
        video_job_id=uuid4(),
        hashtags=["#Python", "python", "#PYTHON", "  #Coding"],
        platform_metadata=_platform_metadata(),
        prompt_version="seo_prompt_v1.0.0",
    )

    assert package.hashtags == ["#python", "#coding"]


def test_seo_package_default_metadata_is_empty_dict() -> None:
    package = SEOPackage(
        video_job_id=uuid4(),
        platform_metadata=_platform_metadata(),
        prompt_version="seo_prompt_v1.0.0",
    )

    assert package.metadata == {}


def test_seo_package_is_ready_for_export_requires_approval_and_content() -> None:
    incomplete_package = SEOPackage(
        video_job_id=uuid4(),
        title_candidates=[TitleCandidate(text="Great Video")],
        selected_title="Great Video",
        description="",
        platform_metadata=_platform_metadata(),
        prompt_version="seo_prompt_v1.0.0",
        status=SEOStatus.APPROVED,
    )

    ready_package = SEOPackage(
        video_job_id=uuid4(),
        title_candidates=[TitleCandidate(text="Great Video")],
        selected_title="Great Video",
        description="A complete, publish-ready description.",
        platform_metadata=_platform_metadata(),
        prompt_version="seo_prompt_v1.0.0",
        status=SEOStatus.APPROVED,
    )

    assert incomplete_package.is_ready_for_export is False
    assert ready_package.is_ready_for_export is True
