from __future__ import annotations

import pytest

from src.models.visual_continuity import (
    CanonicalEntityIdentity,
    CanonicalEntityType,
    ClipContinuityEntry,
    ContinuityConflictType,
    VisualContinuityBible,
    VisualContinuityConflict,
    VisualContinuityValidationResult,
    VisualState,
)


def test_visual_state_defaults_are_explicit_unspecified() -> None:
    state = VisualState()

    assert state.wardrobe == "unspecified"
    assert state.condition == "unspecified"
    assert state.props == []
    assert state.vehicles == []


def test_canonical_entity_identity_rejects_blank_name() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        CanonicalEntityIdentity(
            entity_type=CanonicalEntityType.PERSON,
            name="   ",
            canonical_description="A sailor.",
        )


def test_clip_continuity_entry_rejects_blank_shot_action() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        ClipContinuityEntry(
            scene_number=1,
            incoming_state=VisualState(),
            shot_action="   ",
            outgoing_state=VisualState(),
        )


def test_bible_people_and_locations_filter_by_type() -> None:
    bible = VisualContinuityBible(
        script_lock_hash="hash123",
        identities=[
            CanonicalEntityIdentity(
                entity_type=CanonicalEntityType.PERSON,
                name="Captain Briggs",
                canonical_description="The ship's captain.",
            ),
            CanonicalEntityIdentity(
                entity_type=CanonicalEntityType.LOCATION,
                name="The Mary Celeste",
                canonical_description="A merchant brigantine.",
            ),
        ],
    )

    assert [p.name for p in bible.people] == ["Captain Briggs"]
    assert [loc.name for loc in bible.locations] == ["The Mary Celeste"]


def test_entry_for_scene_finds_by_scene_number() -> None:
    entry = ClipContinuityEntry(
        scene_number=2,
        incoming_state=VisualState(),
        shot_action="The captain surveys the deck.",
        outgoing_state=VisualState(),
    )
    bible = VisualContinuityBible(script_lock_hash="hash123", clip_entries=[entry])

    assert bible.entry_for_scene(2) is entry
    assert bible.entry_for_scene(99) is None


def test_validation_result_is_consistent_when_no_conflicts() -> None:
    result = VisualContinuityValidationResult(script_lock_hash="hash123")

    assert result.is_consistent is True


def test_validation_result_is_inconsistent_with_conflicts() -> None:
    result = VisualContinuityValidationResult(
        script_lock_hash="hash123",
        conflicts=[
            VisualContinuityConflict(
                conflict_type=ContinuityConflictType.HANDOFF_MISMATCH,
                scene_number=2,
                detail="Scene 1 outgoing wardrobe disagrees with scene 2 incoming.",
            )
        ],
    )

    assert result.is_consistent is False
