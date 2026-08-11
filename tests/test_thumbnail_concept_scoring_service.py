from __future__ import annotations

from uuid import uuid4

import pytest

from src.models.enums import Platform
from src.models.thumbnail import ThumbnailConcept
from src.services.seo.seo_context_builder import SEOContext
from src.services.thumbnail.thumbnail_concept_scoring_service import (
    ThumbnailConceptScoringService,
)


def _context(
    *,
    topic: str = "Deep sea creatures",
    script_title: str = "Deep Sea Creatures Explained",
) -> SEOContext:
    return SEOContext(
        video_job_id=uuid4(),
        topic=topic,
        niche="ocean-life",
        genre_id="genre.documentary",
        target_audience="ocean enthusiasts",
        target_country="United States",
        language="English",
        language_code="en",
        platform=Platform.YOUTUBE,
        script_title=script_title,
        script_content="Full script content about deep sea creatures.",
        research_summary="An overview of deep sea creatures.",
        key_facts=["Fact one."],
        scene_count=1,
        estimated_duration_seconds=600,
    )


def _concept(**overrides: object) -> ThumbnailConcept:
    defaults: dict[str, object] = {
        "concept_summary": "A diver facing a giant squid.",
        "hook_text": "GIANT SQUID",
        "visual_prompt": "A deep sea diver facing a giant squid.",
    }
    defaults.update(overrides)

    return ThumbnailConcept(**defaults)  # type: ignore[arg-type]


def test_score_gives_higher_relevance_for_on_topic_concepts() -> None:
    service = ThumbnailConceptScoringService()
    context = _context()

    on_topic = _concept(
        concept_summary="A deep sea creature explained.",
        visual_prompt="Deep sea creatures explained visually.",
    )
    off_topic = _concept(
        concept_summary="A random unrelated scene.",
        visual_prompt="Something completely different.",
    )

    [scored_on_topic, scored_off_topic] = service.score(
        [on_topic, off_topic],
        context,
    )

    assert scored_on_topic.relevance_score > scored_off_topic.relevance_score


def test_score_clarity_favors_short_hook_text() -> None:
    service = ThumbnailConceptScoringService()
    context = _context()

    short = _concept(hook_text="OCEAN SECRET")
    single_word = _concept(hook_text="Ocean")
    long = _concept(hook_text="This Is A Very Long Hook Text Line")

    [scored_short, scored_single, scored_long] = service.score(
        [short, single_word, long],
        context,
    )

    assert scored_short.clarity_score == 100
    assert scored_short.clarity_score > scored_single.clarity_score
    assert scored_short.clarity_score > scored_long.clarity_score


def test_score_curiosity_rewards_hook_words_questions_and_numbers() -> None:
    service = ThumbnailConceptScoringService()
    context = _context()

    plain = _concept(hook_text="Ocean Life")
    hooked = _concept(hook_text="10 Secret Ocean Dangers?")

    [scored_plain, scored_hooked] = service.score([plain, hooked], context)

    assert scored_hooked.curiosity_score > scored_plain.curiosity_score


def test_score_readability_favors_shorter_words() -> None:
    service = ThumbnailConceptScoringService()
    context = _context()

    short_words = _concept(hook_text="Big Sea Cat")
    long_words = _concept(hook_text="Extraordinary Phenomenon Occurrence")

    [scored_short, scored_long] = service.score(
        [short_words, long_words],
        context,
    )

    assert scored_short.text_readability_score > scored_long.text_readability_score


def test_rank_orders_by_overall_score_descending() -> None:
    service = ThumbnailConceptScoringService()

    low = _concept(hook_text="Low", relevance_score=10)
    high = _concept(hook_text="High", relevance_score=90)

    ranked = service.rank([low, high])

    assert [concept.hook_text for concept in ranked] == ["High", "Low"]


def test_rank_tie_breaks_deterministically() -> None:
    service = ThumbnailConceptScoringService()

    concept_a = _concept(hook_text="Zebra Hook", relevance_score=50)
    concept_b = _concept(hook_text="Ant", relevance_score=50)
    concept_c = _concept(hook_text="Bee", relevance_score=50)

    ranked_once = service.rank([concept_a, concept_b, concept_c])
    ranked_again = service.rank([concept_c, concept_a, concept_b])

    assert [concept.hook_text for concept in ranked_once] == [
        "Ant",
        "Bee",
        "Zebra Hook",
    ]
    assert ranked_once == ranked_again


def test_select_best_marks_top_concept_as_selected() -> None:
    service = ThumbnailConceptScoringService()

    low = _concept(hook_text="Low", relevance_score=10)
    high = _concept(hook_text="High", relevance_score=90)

    best = service.select_best([low, high])

    assert best.hook_text == "High"
    assert best.selected is True


def test_select_best_raises_on_empty_concepts() -> None:
    service = ThumbnailConceptScoringService()

    with pytest.raises(ValueError, match="zero concepts"):
        service.select_best([])
