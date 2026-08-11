from __future__ import annotations

from uuid import uuid4

import pytest

from src.models.enums import Platform
from src.models.seo import TitleCandidate
from src.services.seo.seo_context_builder import SEOContext
from src.services.seo.seo_title_scoring_service import (
    SEOTitleScoringService,
)


def _context(
    *,
    topic: str = "Deep sea creatures",
    script_title: str = "Deep Sea Creatures Explained",
    target_audience: str = "ocean enthusiasts",
) -> SEOContext:
    return SEOContext(
        video_job_id=uuid4(),
        topic=topic,
        niche="ocean-life",
        genre_id="genre.documentary",
        target_audience=target_audience,
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


def test_score_gives_higher_relevance_for_on_topic_titles() -> None:
    service = SEOTitleScoringService()
    context = _context()

    on_topic = TitleCandidate(text="Deep Sea Creatures Revealed")
    off_topic = TitleCandidate(text="A Random Unrelated Story")

    [scored_on_topic, scored_off_topic] = service.score(
        [on_topic, off_topic],
        context,
    )

    assert scored_on_topic.relevance_score > scored_off_topic.relevance_score


def test_score_clarity_favors_moderate_length_titles() -> None:
    service = SEOTitleScoringService()
    context = _context()

    moderate = TitleCandidate(text="Exploring Deep Sea Creatures Today")
    too_short = TitleCandidate(text="Ocean")
    too_long = TitleCandidate(
        text=(
            "An Extremely Long And Overly Detailed Title About Deep "
            "Sea Creatures That Goes On And On Forever"
        ),
    )

    [scored_moderate, scored_short, scored_long] = service.score(
        [moderate, too_short, too_long],
        context,
    )

    assert scored_moderate.clarity_score == 100
    assert scored_moderate.clarity_score > scored_short.clarity_score
    assert scored_moderate.clarity_score > scored_long.clarity_score


def test_score_curiosity_rewards_questions_numbers_and_hook_words() -> None:
    service = SEOTitleScoringService()
    context = _context()

    plain = TitleCandidate(text="Deep Sea Creatures")
    hooked = TitleCandidate(text="Why Are 10 Deep Sea Creatures Hidden?")

    [scored_plain, scored_hooked] = service.score([plain, hooked], context)

    assert scored_hooked.curiosity_score > scored_plain.curiosity_score


def test_score_audience_fit_uses_target_audience_overlap() -> None:
    service = SEOTitleScoringService()
    context = _context(target_audience="ocean enthusiasts")

    aligned = TitleCandidate(text="A Guide For Ocean Enthusiasts")
    unaligned = TitleCandidate(text="A Guide For Space Fans")

    [scored_aligned, scored_unaligned] = service.score(
        [aligned, unaligned],
        context,
    )

    assert scored_aligned.audience_fit_score > scored_unaligned.audience_fit_score


def test_score_clickbait_risk_flags_clickbait_phrases() -> None:
    service = SEOTitleScoringService()
    context = _context()

    honest = TitleCandidate(text="Deep Sea Creatures Explained")
    clickbait = TitleCandidate(text="You Won't Believe This Shocking Discovery!!!")

    [scored_honest, scored_clickbait] = service.score(
        [honest, clickbait],
        context,
    )

    assert scored_clickbait.clickbait_risk_score > scored_honest.clickbait_risk_score


def test_rank_orders_by_overall_score_descending() -> None:
    service = SEOTitleScoringService()

    low = TitleCandidate(text="Low", relevance_score=10)
    high = TitleCandidate(text="High", relevance_score=90)

    ranked = service.rank([low, high])

    assert [candidate.text for candidate in ranked] == ["High", "Low"]


def test_rank_tie_breaks_deterministically() -> None:
    service = SEOTitleScoringService()

    # Identical overall_score and relevance_score: tie-break falls to
    # shorter text length, then alphabetical order.
    candidate_a = TitleCandidate(text="Zebra Title", relevance_score=50)
    candidate_b = TitleCandidate(text="Ant", relevance_score=50)
    candidate_c = TitleCandidate(text="Bee", relevance_score=50)

    ranked_once = service.rank([candidate_a, candidate_b, candidate_c])
    ranked_again = service.rank([candidate_c, candidate_a, candidate_b])

    assert [candidate.text for candidate in ranked_once] == [
        "Ant",
        "Bee",
        "Zebra Title",
    ]
    assert ranked_once == ranked_again


def test_select_best_marks_top_candidate_as_selected() -> None:
    service = SEOTitleScoringService()

    low = TitleCandidate(text="Low", relevance_score=10)
    high = TitleCandidate(text="High", relevance_score=90)

    best = service.select_best([low, high])

    assert best.text == "High"
    assert best.selected is True


def test_select_best_raises_on_empty_candidates() -> None:
    service = SEOTitleScoringService()

    with pytest.raises(ValueError, match="zero candidates"):
        service.select_best([])
