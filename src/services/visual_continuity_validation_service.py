from __future__ import annotations

from itertools import pairwise

from src.models.visual_continuity import (
    ContinuityConflictType,
    VisualContinuityBible,
    VisualContinuityConflict,
    VisualContinuityValidationResult,
)


class VisualContinuityValidationService:
    """
    Post-Script-Approval Production Plan, Phase 2: "Add actionable
    continuity conflict diagnostics." Rule-based, no LLM call - the
    same split ContinuityValidationService already established for
    the text-level bible (extraction and validation are separate
    passes).

    Checks the two things VisualContinuityBible's own construction is
    deliberately lenient about: "enforce adjacent handoff equality for
    contiguous clips" and unknown-identity rejection.
    """

    @staticmethod
    def validate(bible: VisualContinuityBible) -> VisualContinuityValidationResult:
        conflicts: list[VisualContinuityConflict] = []

        known_names = {identity.name for identity in bible.identities}
        ordered_entries = sorted(bible.clip_entries, key=lambda e: e.scene_number)

        for entry in ordered_entries:
            for name in entry.entity_names:
                if name not in known_names:
                    conflicts.append(
                        VisualContinuityConflict(
                            conflict_type=ContinuityConflictType.UNKNOWN_IDENTITY,
                            scene_number=entry.scene_number,
                            detail=(
                                f"Scene {entry.scene_number} references "
                                f"'{name}', which has no canonical identity "
                                "in this bible."
                            ),
                        )
                    )

        for current, following in pairwise(ordered_entries):
            if current.outgoing_state != following.incoming_state:
                conflicts.append(
                    VisualContinuityConflict(
                        conflict_type=ContinuityConflictType.HANDOFF_MISMATCH,
                        scene_number=following.scene_number,
                        detail=(
                            f"Scene {current.scene_number}'s outgoing state "
                            f"does not match scene {following.scene_number}'s "
                            "incoming state."
                        ),
                    )
                )

        return VisualContinuityValidationResult(
            script_lock_hash=bible.script_lock_hash,
            conflicts=conflicts,
        )
