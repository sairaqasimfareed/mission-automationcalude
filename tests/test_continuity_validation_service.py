from __future__ import annotations

from src.models.continuity_bible import (
    ContinuityBible,
    ContinuityEntry,
    ContinuityEntryType,
)
from src.services.continuity_validation_service import ContinuityValidationService


def _entry(**overrides: object) -> ContinuityEntry:
    base: dict[str, object] = dict(
        entry_type=ContinuityEntryType.CHARACTER,
        name="Captain Briggs",
        description="Captain of the Mary Celeste.",
        first_mentioned_segment=1,
    )
    base.update(overrides)
    return ContinuityEntry(**base)


def test_validate_flags_two_differing_mentions_of_the_same_name() -> None:
    bible = ContinuityBible(
        topic="The Mary Celeste",
        entries=[
            _entry(
                description="Captain of the Mary Celeste.", first_mentioned_segment=1
            ),
            _entry(
                description="First mate of the Mary Celeste.", first_mentioned_segment=4
            ),
        ],
        prompt_version="continuity_bible_extraction_prompt_v1.0.0",
    )

    result = ContinuityValidationService().validate(bible)

    assert result.is_consistent is False
    assert len(result.inconsistencies) == 1
    inconsistency = result.inconsistencies[0]
    assert inconsistency.name == "Captain Briggs"
    assert inconsistency.first_segment == 1
    assert inconsistency.later_segment == 4


def test_validate_ignores_exact_duplicate_descriptions() -> None:
    bible = ContinuityBible(
        topic="The Mary Celeste",
        entries=[
            _entry(
                description="Captain of the Mary Celeste.", first_mentioned_segment=1
            ),
            _entry(
                description="Captain of the Mary Celeste.", first_mentioned_segment=4
            ),
        ],
        prompt_version="continuity_bible_extraction_prompt_v1.0.0",
    )

    result = ContinuityValidationService().validate(bible)

    assert result.is_consistent is True


def test_validate_treats_names_case_insensitively() -> None:
    bible = ContinuityBible(
        topic="The Mary Celeste",
        entries=[
            _entry(
                name="Captain Briggs",
                description="Captain of the Mary Celeste.",
                first_mentioned_segment=1,
            ),
            _entry(
                name="captain briggs",
                description="A ghost.",
                first_mentioned_segment=4,
            ),
        ],
        prompt_version="continuity_bible_extraction_prompt_v1.0.0",
    )

    result = ContinuityValidationService().validate(bible)

    assert len(result.inconsistencies) == 1


def test_validate_does_not_cross_compare_different_entry_types() -> None:
    bible = ContinuityBible(
        topic="The Mary Celeste",
        entries=[
            _entry(
                entry_type=ContinuityEntryType.CHARACTER,
                name="The Mary Celeste",
                description="A ghostly figure.",
                first_mentioned_segment=1,
            ),
            _entry(
                entry_type=ContinuityEntryType.LOCATION,
                name="The Mary Celeste",
                description="A brigantine ship.",
                first_mentioned_segment=1,
            ),
        ],
        prompt_version="continuity_bible_extraction_prompt_v1.0.0",
    )

    result = ContinuityValidationService().validate(bible)

    assert result.is_consistent is True


def test_validate_with_a_single_mention_is_consistent() -> None:
    bible = ContinuityBible(
        topic="The Mary Celeste",
        entries=[_entry()],
        prompt_version="continuity_bible_extraction_prompt_v1.0.0",
    )

    result = ContinuityValidationService().validate(bible)

    assert result.is_consistent is True


def test_validate_with_no_entries_is_consistent() -> None:
    bible = ContinuityBible(
        topic="The Mary Celeste",
        entries=[],
        prompt_version="continuity_bible_extraction_prompt_v1.0.0",
    )

    result = ContinuityValidationService().validate(bible)

    assert result.is_consistent is True


def test_validate_uses_the_earliest_mention_as_the_baseline() -> None:
    bible = ContinuityBible(
        topic="The Mary Celeste",
        entries=[
            _entry(description="Third description.", first_mentioned_segment=6),
            _entry(description="First description.", first_mentioned_segment=1),
            _entry(description="Second description.", first_mentioned_segment=3),
        ],
        prompt_version="continuity_bible_extraction_prompt_v1.0.0",
    )

    result = ContinuityValidationService().validate(bible)

    assert len(result.inconsistencies) == 2
    assert all(i.first_segment == 1 for i in result.inconsistencies)
    assert all(
        i.first_description == "First description." for i in result.inconsistencies
    )
