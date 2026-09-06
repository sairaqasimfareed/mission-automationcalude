from __future__ import annotations

from uuid import uuid4

import pytest

from src.models.audio_cue_policy import (
    AudioCueConflict,
    AudioCueConflictType,
    AudioCuePolicyResult,
)


def test_is_clean_true_with_no_conflicts() -> None:
    result = AudioCuePolicyResult()

    assert result.is_clean is True


def test_is_clean_false_with_conflicts() -> None:
    result = AudioCuePolicyResult(
        conflicts=[
            AudioCueConflict(
                conflict_type=AudioCueConflictType.REPETITIVE_SFX,
                track_ids=[uuid4(), uuid4()],
                detail="Same SFX used twice within 2 seconds.",
            )
        ]
    )

    assert result.is_clean is False


def test_conflict_requires_at_least_two_track_ids() -> None:
    with pytest.raises(ValueError):
        AudioCueConflict(
            conflict_type=AudioCueConflictType.LOUDNESS_ACCUMULATION,
            track_ids=[uuid4()],
            detail="Not enough tracks to conflict.",
        )
