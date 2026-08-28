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


def test_phase_6_strategy_fields_default_to_none() -> None:
    promise = AudiencePromise(**_kwargs())

    assert promise.persona is None
    assert promise.viewer_intent is None
    assert promise.viewer_promise is None
    assert promise.tone_treatment is None
    assert promise.platform_strategy is None
    assert promise.audience_pain_or_desire is None
    assert promise.knowledge_assumption is None


def test_phase_6_strategy_fields_can_be_set() -> None:
    promise = AudiencePromise(
        **_kwargs(
            persona="A curious armchair detective",
            viewer_intent="Understand what really happened",
            viewer_promise="A satisfying, evidence-backed answer",
            tone_treatment="Measured, investigative",
            platform_strategy="Long-form YouTube deep dive",
            audience_pain_or_desire="Frustrated by shallow retellings",
            knowledge_assumption="Has heard of the ship, knows no details",
        )
    )

    assert promise.persona == "A curious armchair detective"
    assert promise.knowledge_assumption == "Has heard of the ship, knows no details"


def test_phase_6_strategy_fields_normalize_blank_strings_to_none() -> None:
    promise = AudiencePromise(**_kwargs(persona="   ", viewer_intent=""))

    assert promise.persona is None
    assert promise.viewer_intent is None


def test_backward_compatible_round_trip_without_phase_6_fields() -> None:
    """
    A VideoJob JSON file saved before Phase 6 has no persona/
    viewer_intent/etc. keys on its AudiencePromise at all - Pydantic's
    defaults must absorb that silently rather than raising.
    """

    promise = AudiencePromise(**_kwargs())
    raw = promise.model_dump_json()

    reloaded = AudiencePromise.model_validate_json(raw)

    assert reloaded.persona is None
    assert reloaded.viewer_promise is None
