from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.production_ambiguity import (
    AmbiguityResolutionStatus,
    ProductionAmbiguity,
)


def _ambiguity(
    *,
    description: str = "The exact time period is not stated.",
    segment_number: int | None = None,
    continuity_critical: bool = False,
    status: AmbiguityResolutionStatus = AmbiguityResolutionStatus.UNRESOLVED,
    resolution_note: str | None = None,
) -> ProductionAmbiguity:
    return ProductionAmbiguity(
        description=description,
        segment_number=segment_number,
        continuity_critical=continuity_critical,
        status=status,
        resolution_note=resolution_note,
    )


def test_rejects_blank_description() -> None:
    with pytest.raises(ValidationError, match="cannot be empty"):
        _ambiguity(description="   ")


def test_resolved_status_requires_a_resolution_note() -> None:
    with pytest.raises(ValidationError, match="requires a resolution_note"):
        _ambiguity(status=AmbiguityResolutionStatus.RESOLVED_MANUALLY)


def test_resolved_status_with_a_note_constructs() -> None:
    ambiguity = _ambiguity(
        status=AmbiguityResolutionStatus.RESOLVED_MANUALLY,
        resolution_note="Confirmed contemporary setting.",
    )

    assert ambiguity.resolution_note == "Confirmed contemporary setting."


def test_unresolved_status_does_not_require_a_note() -> None:
    ambiguity = _ambiguity()

    assert ambiguity.resolution_note is None


def test_is_blocking_true_only_for_unresolved_continuity_critical() -> None:
    assert _ambiguity(continuity_critical=True).is_blocking is True


def test_is_blocking_false_when_not_continuity_critical() -> None:
    assert _ambiguity(continuity_critical=False).is_blocking is False


def test_is_blocking_false_once_resolved() -> None:
    ambiguity = _ambiguity(
        continuity_critical=True,
        status=AmbiguityResolutionStatus.RESOLVED_BY_AI,
        resolution_note="Decided.",
    )

    assert ambiguity.is_blocking is False
