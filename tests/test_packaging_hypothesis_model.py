from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.packaging_hypothesis import PackagingHypothesis


def _hypothesis(**overrides: object) -> PackagingHypothesis:
    base: dict[str, object] = dict(
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        viewer_promise="You'll learn the leading theory for the crew's fate.",
        title_territories=["The disappearance framing", "The evidence framing"],
        thumbnail_concepts=["Empty deck, fog", "Captain's logbook close-up"],
        curiosity_mechanism="An unresolved question the title poses directly.",
        expected_emotion="Intrigue",
        differentiation_angle="Focuses on the physical evidence, not folklore.",
        prompt_version="packaging_hypothesis_prompt_v1.0.0",
    )
    base.update(overrides)
    return PackagingHypothesis(**base)


def test_valid_hypothesis_constructs() -> None:
    hypothesis = _hypothesis()

    assert hypothesis.topic == "The Mary Celeste"
    assert len(hypothesis.title_territories) == 2


def test_rejects_genre_id_without_prefix() -> None:
    with pytest.raises(ValidationError):
        _hypothesis(genre_id="mystery")


def test_rejects_empty_title_territories() -> None:
    with pytest.raises(ValidationError):
        _hypothesis(title_territories=[])


def test_rejects_title_territories_that_are_all_blank() -> None:
    with pytest.raises(ValidationError):
        _hypothesis(title_territories=["   ", "  "])


def test_deduplicates_thumbnail_concepts() -> None:
    hypothesis = _hypothesis(
        thumbnail_concepts=["Empty deck, fog", "Empty deck, fog", "Second concept"]
    )

    assert hypothesis.thumbnail_concepts == ["Empty deck, fog", "Second concept"]
