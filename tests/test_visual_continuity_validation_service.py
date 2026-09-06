from __future__ import annotations

from src.models.visual_continuity import (
    CanonicalEntityIdentity,
    CanonicalEntityType,
    ClipContinuityEntry,
    VisualContinuityBible,
    VisualState,
)
from src.services.visual_continuity_validation_service import (
    VisualContinuityValidationService,
)


def _identity(name: str) -> CanonicalEntityIdentity:
    return CanonicalEntityIdentity(
        entity_type=CanonicalEntityType.PERSON,
        name=name,
        canonical_description="A recurring character.",
    )


def test_consistent_bible_has_no_conflicts() -> None:
    handoff_state = VisualState(wardrobe="Uniform")
    bible = VisualContinuityBible(
        script_lock_hash="hash123",
        identities=[_identity("Captain Briggs")],
        clip_entries=[
            ClipContinuityEntry(
                scene_number=1,
                incoming_state=VisualState(),
                shot_action="The captain surveys.",
                outgoing_state=handoff_state,
                entity_names=["Captain Briggs"],
            ),
            ClipContinuityEntry(
                scene_number=2,
                incoming_state=handoff_state,
                shot_action="Clouds gather.",
                outgoing_state=handoff_state,
                entity_names=["Captain Briggs"],
            ),
        ],
    )

    result = VisualContinuityValidationService.validate(bible)

    assert result.is_consistent is True
    assert result.conflicts == []


def test_handoff_mismatch_is_detected() -> None:
    bible = VisualContinuityBible(
        script_lock_hash="hash123",
        identities=[],
        clip_entries=[
            ClipContinuityEntry(
                scene_number=1,
                incoming_state=VisualState(),
                shot_action="The captain surveys.",
                outgoing_state=VisualState(wardrobe="Uniform"),
            ),
            ClipContinuityEntry(
                scene_number=2,
                incoming_state=VisualState(wardrobe="Nightgown"),
                shot_action="Clouds gather.",
                outgoing_state=VisualState(wardrobe="Nightgown"),
            ),
        ],
    )

    result = VisualContinuityValidationService.validate(bible)

    assert result.is_consistent is False
    assert len(result.conflicts) == 1
    assert result.conflicts[0].conflict_type.value == "handoff_mismatch"
    assert result.conflicts[0].scene_number == 2


def test_unknown_identity_is_detected() -> None:
    bible = VisualContinuityBible(
        script_lock_hash="hash123",
        identities=[_identity("Captain Briggs")],
        clip_entries=[
            ClipContinuityEntry(
                scene_number=1,
                incoming_state=VisualState(),
                shot_action="A stranger appears.",
                outgoing_state=VisualState(),
                entity_names=["Unknown Sailor"],
            ),
        ],
    )

    result = VisualContinuityValidationService.validate(bible)

    assert result.is_consistent is False
    assert result.conflicts[0].conflict_type.value == "unknown_identity"
    assert "Unknown Sailor" in result.conflicts[0].detail


def test_empty_bible_is_consistent() -> None:
    bible = VisualContinuityBible(script_lock_hash="hash123")

    result = VisualContinuityValidationService.validate(bible)

    assert result.is_consistent is True
