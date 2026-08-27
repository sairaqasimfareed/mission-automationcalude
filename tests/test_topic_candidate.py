from __future__ import annotations

import pytest

from src.models.topic_candidate import TopicCandidate


def test_overall_score_averages_the_six_dimensions() -> None:
    candidate = TopicCandidate(
        title="The Mary Celeste's missing crew",
        audience_potential=80,
        specificity=70,
        novelty=60,
        story_potential=90,
        researchability=50,
        platform_fit=60,
    )

    assert candidate.overall_score == pytest.approx((80 + 70 + 60 + 90 + 50 + 60) / 6)


def test_overall_score_is_none_when_any_dimension_is_unset() -> None:
    candidate = TopicCandidate(title="Partially scored topic", audience_potential=80)

    assert candidate.overall_score is None


def test_custom_topic_has_no_scores_and_is_flagged_custom() -> None:
    candidate = TopicCandidate.custom("The lighthouse keeper who vanished")

    assert candidate.is_custom is True
    assert candidate.overall_score is None
    assert candidate.ai_recommendation is None
    assert candidate.audience_potential is None


def test_blank_title_is_rejected() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        TopicCandidate(title="   ")


def test_blank_ai_recommendation_is_normalized_to_none() -> None:
    candidate = TopicCandidate(
        title="A topic",
        audience_potential=1,
        specificity=1,
        novelty=1,
        story_potential=1,
        researchability=1,
        platform_fit=1,
        ai_recommendation="   ",
    )

    assert candidate.ai_recommendation is None


def test_backward_compatible_round_trip_from_json_without_topic_fields() -> None:
    """
    A VideoJob JSON file saved before Phase 5 has no topic_candidates
    or selected_topic_candidate keys at all - Pydantic's default_factory
    must absorb that silently rather than raising.
    """

    from src.models.video_job import VideoJob

    job = VideoJob(
        project_name="p",
        channel_name="c",
        niche="n",
        topic="t",
    )
    raw = job.model_dump_json()

    reloaded = VideoJob.model_validate_json(raw)

    assert reloaded.topic_candidates == []
    assert reloaded.selected_topic_candidate is None
