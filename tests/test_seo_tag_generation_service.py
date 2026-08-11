from __future__ import annotations

from uuid import uuid4

import pytest

from src.models.enums import Platform
from src.models.seo import SEOKeywordSet
from src.services.seo.seo_context_builder import SEOContext
from src.services.seo.seo_tag_generation_service import (
    SEOTagGenerationService,
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
        secondary_keywords=["whale", "reef"],
        long_tail_keywords=["deep sea creatures"],
    )


def test_generate_includes_topic_niche_and_keywords() -> None:
    service = SEOTagGenerationService()

    tags = service.generate(_context(), _keywords())

    assert "deep sea creatures" in tags
    assert "ocean-life" in tags
    assert "ocean" in tags
    assert "shark" in tags
    assert "whale" in tags
    assert "reef" in tags


def test_generate_deduplicates_case_insensitively() -> None:
    service = SEOTagGenerationService()

    context = _context()
    keywords = SEOKeywordSet(
        primary_keywords=["ocean-life", "ocean"],
        secondary_keywords=[],
        long_tail_keywords=[],
    )

    tags = service.generate(context, keywords)

    assert tags.count("ocean-life") == 1


def test_generate_respects_max_tags() -> None:
    service = SEOTagGenerationService()

    tags = service.generate(_context(), _keywords(), max_tags=2)

    assert len(tags) == 2


def test_generate_rejects_negative_max_tags() -> None:
    service = SEOTagGenerationService()

    with pytest.raises(ValueError, match="cannot be negative"):
        service.generate(_context(), _keywords(), max_tags=-1)


def test_generate_is_deterministic() -> None:
    service = SEOTagGenerationService()
    context = _context()
    keywords = _keywords()

    assert service.generate(context, keywords) == service.generate(
        context,
        keywords,
    )
