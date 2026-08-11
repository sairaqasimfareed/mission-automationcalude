from __future__ import annotations

from uuid import uuid4

import pytest

from src.models.enums import Platform
from src.services.seo.seo_context_builder import SEOContext
from src.services.seo.seo_keyword_generation_service import (
    SEOKeywordGenerationService,
)


def _context(
    *,
    script_content: str = "ocean ocean ocean shark shark whale",
) -> SEOContext:
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
        script_content=script_content,
        research_summary="An overview of deep sea creatures.",
        key_facts=["Fact one."],
        scene_count=1,
        estimated_duration_seconds=600,
    )


def test_generate_ranks_words_by_frequency() -> None:
    service = SEOKeywordGenerationService()

    keywords = service.generate(_context(), primary_count=1)

    assert keywords.primary_keywords == ["ocean"]


def test_generate_excludes_stopwords() -> None:
    service = SEOKeywordGenerationService()

    context = _context(script_content="the ocean and the shark are amazing")

    keywords = service.generate(
        context,
        primary_count=10,
        secondary_count=0,
    )

    assert "the" not in keywords.primary_keywords
    assert "and" not in keywords.primary_keywords
    assert "are" not in keywords.primary_keywords


def test_generate_respects_bounded_counts() -> None:
    service = SEOKeywordGenerationService()

    context = _context(
        script_content="alpha bravo charlie delta echo foxtrot golf hotel",
    )

    keywords = service.generate(
        context,
        primary_count=2,
        secondary_count=3,
        long_tail_count=1,
    )

    assert len(keywords.primary_keywords) == 2
    assert len(keywords.secondary_keywords) == 3
    assert len(keywords.long_tail_keywords) == 1


def test_generate_ties_break_alphabetically() -> None:
    service = SEOKeywordGenerationService()

    context = _context(script_content="zebra apple mango")

    # All three words appear once, tying with each other (and with
    # other single-occurrence context words) - isolate just these
    # three to confirm frequency ties break alphabetically.
    keywords = service.generate(context, primary_count=20, secondary_count=0)

    relevant = [
        word
        for word in keywords.primary_keywords
        if word in {"zebra", "apple", "mango"}
    ]

    assert relevant == ["apple", "mango", "zebra"]


def test_generate_long_tail_keywords_are_two_word_phrases() -> None:
    service = SEOKeywordGenerationService()

    context = _context(script_content="deep sea creatures explained")

    keywords = service.generate(
        context,
        primary_count=0,
        secondary_count=0,
        long_tail_count=5,
    )

    assert all(" " in phrase for phrase in keywords.long_tail_keywords)


def test_generate_is_deterministic_across_calls() -> None:
    # SEOKeywordSet inherits MissionBaseModel's random id/timestamp
    # fields, so two independently constructed instances are never
    # equal via `==` even with identical content - compare the
    # meaningful fields directly instead.
    service = SEOKeywordGenerationService()
    context = _context()

    first = service.generate(context)
    second = service.generate(context)

    assert first.primary_keywords == second.primary_keywords
    assert first.secondary_keywords == second.secondary_keywords
    assert first.long_tail_keywords == second.long_tail_keywords


def test_generate_rejects_negative_counts() -> None:
    service = SEOKeywordGenerationService()

    with pytest.raises(ValueError, match="cannot be negative"):
        service.generate(_context(), primary_count=-1)
