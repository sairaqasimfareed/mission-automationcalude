from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.elevenlabs_voice_alignment import (
    ElevenLabsVoiceCharacterAlignment,
    ElevenLabsVoiceWithTimestampsResult,
)


def test_constructs_with_matching_lengths() -> None:
    alignment = ElevenLabsVoiceCharacterAlignment(
        characters=["H", "i"],
        character_start_times_seconds=[0.0, 0.1],
        character_end_times_seconds=[0.1, 0.2],
    )

    assert alignment.character_count == 2


def test_defaults_to_empty_lists() -> None:
    alignment = ElevenLabsVoiceCharacterAlignment()

    assert alignment.character_count == 0
    assert alignment.characters == []


def test_rejects_mismatched_array_lengths() -> None:
    with pytest.raises(ValidationError, match="same length"):
        ElevenLabsVoiceCharacterAlignment(
            characters=["H", "i"],
            character_start_times_seconds=[0.0],
            character_end_times_seconds=[0.1, 0.2],
        )


def test_with_timestamps_result_allows_null_alignment() -> None:
    result = ElevenLabsVoiceWithTimestampsResult(output_file="voice.mp3")

    assert result.alignment is None
    assert result.normalized_alignment is None


def test_with_timestamps_result_round_trips_through_json() -> None:
    result = ElevenLabsVoiceWithTimestampsResult(
        output_file="voice.mp3",
        alignment=ElevenLabsVoiceCharacterAlignment(
            characters=["H"],
            character_start_times_seconds=[0.0],
            character_end_times_seconds=[0.1],
        ),
    )

    restored = ElevenLabsVoiceWithTimestampsResult.model_validate_json(
        result.model_dump_json()
    )

    assert restored == result
