from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.generated_script import GeneratedScript, ScriptSegment
from src.models.script_intake import (
    ScriptIntakeMismatch,
    ScriptIntakeMode,
    ScriptIntakeResult,
)
from src.models.story_blueprint import StoryBeatType


def _script() -> GeneratedScript:
    return GeneratedScript(
        topic="Imported Topic",
        genre_id="genre.mystery",
        target_duration_seconds=180,
        segments=[
            ScriptSegment(
                segment_number=1,
                start_seconds=0,
                end_seconds=30,
                narrative_function=StoryBeatType.SETUP,
                narration="An imported opening line.",
                tension_level=50,
            )
        ],
        prompt_version="script_intake_prompt_v1.0.0",
    )


def _mismatch(
    *,
    field: str = "language",
    expected: str = "English",
    detected: str = "French",
    note: str = "The imported script's language does not match.",
) -> ScriptIntakeMismatch:
    return ScriptIntakeMismatch(
        field=field, expected=expected, detected=detected, note=note
    )


def _result(
    *,
    mode: ScriptIntakeMode = ScriptIntakeMode.VALIDATE_FOR_PRODUCTION,
    estimated_duration_seconds: float = 30.0,
    target_duration_seconds: int = 180,
    mismatches: list[ScriptIntakeMismatch] | None = None,
) -> ScriptIntakeResult:
    return ScriptIntakeResult(
        mode=mode,
        script=_script(),
        word_count=_script().word_count,
        estimated_duration_seconds=estimated_duration_seconds,
        target_duration_seconds=target_duration_seconds,
        mismatches=mismatches if mismatches is not None else [],
    )


def test_mismatch_rejects_blank_fields() -> None:
    with pytest.raises(ValidationError):
        _mismatch(note="   ")


def test_duration_mismatch_seconds_is_the_absolute_difference() -> None:
    result = _result(estimated_duration_seconds=30.0, target_duration_seconds=180)

    assert result.duration_mismatch_seconds == 150.0


def test_duration_mismatch_ratio() -> None:
    result = _result(estimated_duration_seconds=90.0, target_duration_seconds=180)

    assert result.duration_mismatch_ratio == pytest.approx(0.5)


def test_has_significant_duration_mismatch_above_20_percent() -> None:
    result = _result(estimated_duration_seconds=100.0, target_duration_seconds=180)

    assert result.has_significant_duration_mismatch is True


def test_has_significant_duration_mismatch_false_within_20_percent() -> None:
    result = _result(estimated_duration_seconds=170.0, target_duration_seconds=180)

    assert result.has_significant_duration_mismatch is False


def test_result_carries_the_mode() -> None:
    result = _result(mode=ScriptIntakeMode.TRUST_MY_SCRIPT)

    assert result.mode == ScriptIntakeMode.TRUST_MY_SCRIPT


def test_result_carries_mismatches() -> None:
    mismatch = _mismatch()
    result = _result(mismatches=[mismatch])

    assert result.mismatches == [mismatch]
