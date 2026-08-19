from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.continuity_bible import (
    ContinuityBible,
    ContinuityEntry,
    ContinuityEntryType,
    ContinuityInconsistency,
    ContinuityValidationResult,
)


def _entry(**overrides: object) -> ContinuityEntry:
    base: dict[str, object] = dict(
        entry_type=ContinuityEntryType.CHARACTER,
        name="Captain Briggs",
        description="Captain of the Mary Celeste.",
        first_mentioned_segment=1,
    )
    base.update(overrides)
    return ContinuityEntry(**base)


def test_entry_rejects_empty_name() -> None:
    with pytest.raises(ValidationError):
        _entry(name="   ")


def test_entry_rejects_empty_description() -> None:
    with pytest.raises(ValidationError):
        _entry(description="   ")


def test_bible_filters_entries_by_type() -> None:
    bible = ContinuityBible(
        topic="The Mary Celeste",
        entries=[
            _entry(entry_type=ContinuityEntryType.CHARACTER, name="Captain Briggs"),
            _entry(
                entry_type=ContinuityEntryType.LOCATION,
                name="The Mary Celeste",
                description="A brigantine ship.",
            ),
            _entry(
                entry_type=ContinuityEntryType.TIMELINE,
                name="November 1872",
                description="When the ship departed New York.",
            ),
            _entry(
                entry_type=ContinuityEntryType.FACT,
                name="No struggle found",
                description="No signs of struggle were found on deck.",
            ),
        ],
        prompt_version="continuity_bible_extraction_prompt_v1.0.0",
    )

    assert [e.name for e in bible.characters] == ["Captain Briggs"]
    assert [e.name for e in bible.locations] == ["The Mary Celeste"]
    assert [e.name for e in bible.timeline_facts] == ["November 1872"]
    assert [e.name for e in bible.facts] == ["No struggle found"]


def test_validation_result_with_no_inconsistencies_is_consistent() -> None:
    result = ContinuityValidationResult(topic="The Mary Celeste")

    assert result.is_consistent is True


def test_validation_result_with_inconsistencies_is_not_consistent() -> None:
    result = ContinuityValidationResult(
        topic="The Mary Celeste",
        inconsistencies=[
            ContinuityInconsistency(
                entry_type=ContinuityEntryType.CHARACTER,
                name="Captain Briggs",
                first_description="Captain of the Mary Celeste.",
                first_segment=1,
                later_description="First mate of the Mary Celeste.",
                later_segment=4,
            )
        ],
    )

    assert result.is_consistent is False
