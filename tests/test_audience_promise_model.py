from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.audience_promise import AudiencePromise, PromiseStrength


def _kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = dict(
        topic="The Mary Celeste",
        target_audience="Mystery enthusiasts",
        platform="youtube",
        genre_id="genre.mystery",
        target_duration_seconds=180,
        intended_emotion="Dread",
        central_curiosity="Why did the crew vanish?",
        primary_question="What really happened aboard the ship?",
        viewer_benefit="A satisfying, verified explanation.",
        expected_payoff="The disputed final theory.",
        promise_strength=PromiseStrength.STRONG,
        prompt_version="audience_promise_prompt_v1.0.0",
    )
    base.update(overrides)
    return base


def test_valid_promise_constructs() -> None:
    promise = AudiencePromise(**_kwargs())

    assert promise.genre_id == "genre.mystery"
    assert promise.is_weak is False


def test_genre_id_must_start_with_genre_prefix() -> None:
    with pytest.raises(ValidationError, match="must start with 'genre.'"):
        AudiencePromise(**_kwargs(genre_id="mystery"))


def test_genre_id_is_normalized_to_lowercase() -> None:
    promise = AudiencePromise(**_kwargs(genre_id="GENRE.Mystery"))

    assert promise.genre_id == "genre.mystery"


def test_target_duration_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        AudiencePromise(**_kwargs(target_duration_seconds=0))


@pytest.mark.parametrize(
    "strength,expected_score,expected_weak",
    [
        (PromiseStrength.STRONG, 0.9, False),
        (PromiseStrength.MODERATE, 0.6, False),
        (PromiseStrength.WEAK, 0.25, True),
    ],
)
def test_confidence_score_and_is_weak_per_strength(
    strength: PromiseStrength,
    expected_score: float,
    expected_weak: bool,
) -> None:
    promise = AudiencePromise(**_kwargs(promise_strength=strength))

    assert promise.confidence_score == expected_score
    assert promise.is_weak is expected_weak


def test_required_text_fields_reject_empty_string() -> None:
    with pytest.raises(ValidationError):
        AudiencePromise(**_kwargs(central_curiosity=""))
