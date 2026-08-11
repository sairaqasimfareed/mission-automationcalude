from __future__ import annotations

from uuid import uuid4

import pytest

from src.models.enums import Platform
from src.models.seo import SEOKeywordSet
from src.services.seo.seo_context_builder import SEOContext
from src.services.seo.seo_hashtag_generation_service import (
    SEOHashtagGenerationService,
)


def _context() -> SEOContext:
    return SEOContext(
        video_job_id=uuid4(),
        topic="Deep sea creatures",
        niche="ocean-life",
        genre_id="genre.documentary",
        target_audience="Ocean enthusiasts",
        target_country="United States",
        language="English",
        language_code="en",
        platform=Platform.YOUTUBE,
        script_title="Deep Sea Creatures Explained",
        script_content="Full script content.",
        research_summary="An overview.",
        key_facts=[],
        scene_count=1,
        estimated_duration_seconds=600,
    )


def _keywords() -> SEOKeywordSet:
    return SEOKeywordSet(
        primary_keywords=["ocean", "shark"],
        secondary_keywords=["whale"],
        long_tail_keywords=["deep sea creatures"],
    )


def test_generate_produces_single_token_hashtags() -> None:
    service = SEOHashtagGenerationService()

    hashtags = service.generate(_context(), _keywords())

    assert "#oceanlife" in hashtags
    assert "#deepseacreatures" in hashtags
    assert "#ocean" in hashtags
    assert "#shark" in hashtags
    assert "#whale" in hashtags

    for hashtag in hashtags:
        assert " " not in hashtag
        assert hashtag.startswith("#")


def test_generate_strips_non_alphanumeric_characters() -> None:
    service = SEOHashtagGenerationService()

    hashtags = service.generate(_context(), _keywords())

    assert "#oceanlife" in hashtags
    assert "#ocean-life" not in hashtags


def test_generate_deduplicates_after_normalization() -> None:
    service = SEOHashtagGenerationService()

    context = _context()
    keywords = SEOKeywordSet(
        primary_keywords=["ocean life", "OceanLife"],
        secondary_keywords=[],
        long_tail_keywords=[],
    )

    hashtags = service.generate(context, keywords)

    assert hashtags.count("#oceanlife") == 1


def test_generate_respects_max_hashtags() -> None:
    service = SEOHashtagGenerationService()

    hashtags = service.generate(_context(), _keywords(), max_hashtags=2)

    assert len(hashtags) == 2


def test_generate_rejects_negative_max_hashtags() -> None:
    service = SEOHashtagGenerationService()

    with pytest.raises(ValueError, match="cannot be negative"):
        service.generate(_context(), _keywords(), max_hashtags=-1)


def test_generate_is_deterministic() -> None:
    service = SEOHashtagGenerationService()
    context = _context()
    keywords = _keywords()

    assert service.generate(context, keywords) == service.generate(
        context,
        keywords,
    )
